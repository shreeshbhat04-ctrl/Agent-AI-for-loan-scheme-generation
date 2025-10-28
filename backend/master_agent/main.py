import uvicorn
import httpx
import logging
import json
import re
import asyncio
import os
from collections import defaultdict
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- NEW Imports for LangGraph ---
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.message import add_messages
from typing import TypedDict, List, Annotated
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool, StructuredTool
from langchain_google_genai import ChatGoogleGenerativeAI

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
# Create a dictionary that automatically creates a new lock for any new user
user_locks = defaultdict(asyncio.Lock)

# --- Agent and Service URLs (Unchanged) ---
AGENT_URLS = {
    "sales": "http://127.0.0.1:8001/sales",
    "verification": "http://127.0.0.1:8002/verify",
    "underwriting": "http://127.0.0.1:8003/underwrite",
    "sanction": "http://127.0.0.1:8004/sanction",
}

# --- Gemini API Configuration ---
# Get API key from environment variable
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
if not GOOGLE_API_KEY:
    logger.warning("GOOGLE_API_KEY not set. Please create a .env file with your API key.")

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash-preview-09-2025",
    google_api_key=GOOGLE_API_KEY,
    convert_system_message_to_human=True
)

# --- Global variables ---
app_http_client = None
app_graph = None
memory_saver = None # Added for reset

# --- Pydantic Models ---
class ChatRequest(BaseModel):
    customer_id: str
    message: str

# === LANGGRAPH IMPLEMENTATION ===

# --- 1. Define Tools ---
@tool
async def tool_get_sales_offer(customer_id: str) -> dict:
    """Must be called first. Gets the pre-approved loan offer for a customer. Returns the pre-approved limit and interest rates."""
    logger.info(f"LangGraph: Calling Sales Agent for {customer_id}")
    url = AGENT_URLS["sales"]
    response = await app_http_client.post(url, json={"customer_id": customer_id})
    response.raise_for_status()
    return response.json()

@tool
async def tool_verify_kyc(customer_id: str) -> dict:
    """Calls the Verification Agent to check the customer's KYC status. Must be called *before* underwriting."""
    logger.info(f"LangGraph: Calling Verification Agent for {customer_id}")
    url = AGENT_URLS["verification"]
    response = await app_http_client.post(url, json={"customer_id": customer_id})
    response.raise_for_status()
    return response.json()

@tool
async def tool_run_underwriting(
    customer_id: str, 
    requested_loan_amount: int, 
    pre_approved_limit: int, 
    monthly_salary: int, 
    interest_rate: float, 
    loan_tenure_months: int
) -> dict:
    """Calls the Underwriting Agent to get a final 'approved' or 'rejected' decision. Requires all loan parameters."""
    logger.info(f"LangGraph: Calling Underwriting Agent for {customer_id}")
    url = AGENT_URLS["underwriting"]
    payload = {
        "customer_id": customer_id,
        "requested_loan_amount": requested_loan_amount,
        "pre_approved_limit": pre_approved_limit,
        "monthly_salary": monthly_salary,
        "interest_rate": interest_rate,
        "loan_tenure_months": loan_tenure_months
    }
    response = await app_http_client.post(url, json=payload)
    response.raise_for_status()
    return response.json()

@tool
async def tool_generate_sanction(
    customer_id: str, 
    loan_amount: int, 
    interest_rate: float, 
    tenure_months: int
) -> dict:
    """Calls the Sanction Agent to generate the final PDF letter. Only call this *after* the user is approved and confirms they want the letter."""
    logger.info(f"LangGraph: Calling Sanction Agent for {customer_id}")
    url = AGENT_URLS["sanction"]
    payload = {
        "customer_id": customer_id,
        "loan_amount": loan_amount,
        "interest_rate": interest_rate,
        "tenure_months": tenure_months
    }
    response = await app_http_client.post(url, json=payload)
    response.raise_for_status()
    relative_path = response.json().get('file_path', 'N/A')
    if relative_path != 'N/A':
        relative_path = relative_path.replace("../../", "")
    return {"status": "success", "file_path": relative_path}

tools = [
    tool_get_sales_offer, 
    tool_verify_kyc, 
    tool_run_underwriting, 
    tool_generate_sanction
]

# --- 2. System Prompt ---
SYSTEM_PROMPT = """
You are a friendly and professional loan sales assistant. Your name is LoanBot.
The user's customer_id will be provided in the first human message.
You *must* follow these rules to process a loan:

1.  **GREET & OFFER:** Greet the user. Your *first* action MUST be to call `tool_get_sales_offer` with the `customer_id`.
2.  **ASK AMOUNT:** After getting the offer, you *must* inform the user of their `pre_approved_limit` and `interest_rate_str` and ask 'How much would you like to apply for?'.
3.  **CHECK AMOUNT (CRITICAL):** When the user provides a `requested_amount` (e.g., "50000" or "fifty thousand"), you *must* follow this logic:
    * **IF `requested_amount` > (2 * `pre_approved_limit`):** You *must* reject them. Tell them the amount is more than 2x their limit. Do NOT call any other tools.
    * **IF `pre_approved_limit` < `requested_amount` <= (2 * `pre_approved_limit`):** You *must* ask for their `monthly_salary`. Do NOT proceed until you have it. (e.g. "I make 75k" or "75000").
    * **IF `requested_amount` <= `pre_approved_limit`:** This is the easy path. You can skip the salary step. Proceed to Step 4.
4.  **VERIFY KYC:** *After* you have the `requested_amount` (and `monthly_salary` if required), your next action *must* be to call `tool_verify_kyc`.
5.  **RUN UNDERWRITING:** *Only if* KYC status is 'verified', you *must* call `tool_run_underwriting`.
    * For the easy path (no salary), pass `monthly_salary=0`.
    * For the salary path, pass the salary they gave you.
    * Always pass `loan_tenure_months=36`.
    * The `interest_rate` is the *float value* (e.g., 8.5) from the sales offer.
6.  **REPORT DECISION:** Report the underwriting `status` (approved/rejected) and `reason` to the user.
7.  **SANCTION:** *Only if* the status is 'approved', ask the user if they want the sanction letter. If they say yes, call `tool_generate_sanction`.

You can handle natural language for amounts (e.g., "fifty thousand" -> 50000).
Be polite and guide the user step-by-step.
"""

# --- 3. Define The Graph State ---
class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]

# --- 4. Define The Graph Nodes ---
async def call_model(state: AgentState):
    """The 'agent' node: calls the LLM to decide the next action."""
    messages = state['messages']
    
    logger.info(f"call_model: Processing {len(messages)} messages")
    
    # Log message types for debugging
    for idx, msg in enumerate(messages):
        logger.info(f"Message {idx}: type={type(msg).__name__}, has_content={hasattr(msg, 'content')}")
    
    # Validate that we have messages to send
    if not messages or len(messages) == 0:
        logger.error("No messages in state - cannot call LLM")
        # Return a default error message
        error_msg = AIMessage(content="I encountered an error processing your request. Please try again.")
        return {"messages": [error_msg]}
    
    # === ENABLE TOOLS ===
    # Bind tools to enable tool calling
    try:
        # Use .bind_tools() which is the newer API for langchain-google-genai 3.0.0
        if hasattr(llm, 'bind_tools'):
            llm_with_tools = llm.bind_tools(tools)
        else:
            llm_with_tools = llm.bind(tools=tools)
        
        logger.info(f"Tools bound successfully. Calling LLM with {len(tools)} tools.")
        response = await llm_with_tools.ainvoke(messages)
    except Exception as e:
        # If tool binding fails, log the error but continue
        logger.error(f"Error binding tools or calling LLM: {e}")
        logger.warning("Retrying without tools...")
        
        # Retry without tools
        try:
            response = await llm.ainvoke(messages)
        except Exception as llm_err:
            logger.error(f"Error calling LLM without tools: {llm_err}")
            # Return a default message
            error_msg = AIMessage(content="I'm having trouble processing your request right now. Please try again.")
            return {"messages": [error_msg]}
    
    return {"messages": [response]}

async def call_tool(state: AgentState):
    """The 'tools' node: executes the tool call decided by the LLM."""
    last_message = state['messages'][-1]
    if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
        return {"messages": []}
    
    tool_messages = []
    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]
        logger.info(f"LangGraph: Executing tool '{tool_name}' with args {tool_args}")
        
        tool_func = next((t for t in tools if t.name == tool_name), None)
        if not tool_func:
            tool_messages.append(ToolMessage(
                content=f"Error: Unknown tool {tool_name}", 
                tool_call_id=tool_call["id"]
            ))
            continue
            
        try:
            result = await tool_func.ainvoke(tool_args)
            tool_messages.append(ToolMessage(
                content=json.dumps(result), 
                tool_call_id=tool_call["id"]
            ))
        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {e}")
            tool_messages.append(ToolMessage(
                content=f"Error: {e}", 
                tool_call_id=tool_call["id"]
            ))
            
    return {"messages": tool_messages}

# --- 5. Define The Graph Edges ---
def should_continue(state: AgentState):
    """Decides whether to call a tool or end the turn."""
    if not state['messages']:
        return END
    
    last_message = state['messages'][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"
    return END

# --- HTTP Client Lifecycle ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    global app_http_client, app_graph, memory_saver
    
    # Initialize HTTP client
    app_http_client = httpx.AsyncClient()
    
    # Initialize in-memory checkpointer
    memory_saver = MemorySaver()
    
    # Build the workflow
    workflow = StateGraph(AgentState)
    # === THIS IS THE FIX ===
    # Changed add__node (with two underscores) to add_node (with one)
    workflow.add_node("agent", call_model)
    workflow.add_node("tools", call_tool)
    workflow.set_entry_point("agent")
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            END: END,
        },
    )
    workflow.add_edge("tools", "agent")
    
    # Compile with memory checkpointer
    app_graph = workflow.compile(checkpointer=memory_saver)
    
    logger.info("LangGraph workflow compiled successfully with MemorySaver")
    
    yield
    
    # Cleanup
    await app_http_client.close()

# === END OF LANGGRAPH IMPLEMENTATION ===

# --- FastAPI App & CORS ---
app = FastAPI(title="Loan Chatbot - LangGraph Master Agent", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"message": "LangGraph Master Agent API is live!"}

# === THIS IS THE FIX ===
# Changed @app.post to @app.get to allow browser access
@app.get("/reset/{customer_id}")
async def reset_conversation(customer_id: str):
    """
    Resets the conversation state for a customer.
    This is CRITICAL for fixing the "Timestamps" error.
    For LangGraph 0.0.48 with MemorySaver, we need to access the internal storage.
    """
    global memory_saver
    try:
        config = {"configurable": {"thread_id": customer_id}}
        
        # Clear MemorySaver state for this thread
        # In LangGraph 0.0.48, MemorySaver uses either _storage or storage dict
        cleared = False
        if memory_saver:
            # Try _storage (private attribute)
            if hasattr(memory_saver, '_storage') and isinstance(memory_saver._storage, dict):
                if customer_id in memory_saver._storage:
                    del memory_saver._storage[customer_id]
                    cleared = True
            # Try storage (alternative attribute name)
            elif hasattr(memory_saver, 'storage') and isinstance(memory_saver.storage, dict):
                if customer_id in memory_saver.storage:
                    del memory_saver.storage[customer_id]
                    cleared = True
            
            if cleared:
                logger.info(f"Reset conversation for customer {customer_id}")
                return {"message": f"Conversation reset for customer {customer_id}"}
            else:
                logger.warning(f"Could not find customer state to reset for {customer_id}")
                return {"message": f"No active conversation found for customer {customer_id}"}
        else:
            return {"message": "MemorySaver not initialized"}
    except Exception as e:
        logger.error(f"Error resetting conversation for {customer_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat")
async def chat(request: ChatRequest):
    """
    Chat endpoint using LangGraph.
    The customer_id is used as the thread_id for conversation memory.
    """
    global app_graph, memory_saver
    customer_id = request.customer_id
    message = request.message
    
    config = {"configurable": {"thread_id": customer_id}}
    lock = user_locks[customer_id]

    async with lock:
        try:
            # Check if this is the first message
            try:
                current_state = await app_graph.aget_state(config)
                is_first_message = not current_state or not current_state.values or not current_state.values.get('messages')
            except Exception as state_err:
                # If we can't get state, assume it's a new conversation
                logger.warning(f"Could not get state: {state_err}. Assuming new conversation.")
                is_first_message = True
            
            if is_first_message:
                logger.info(f"Starting new conversation for customer {customer_id}")
                # First message - include customer_id AND system prompt
                if message.lower().strip() in ['hi', 'hello', 'start', '']:
                    user_message_content = f"{SYSTEM_PROMPT}\n\nMy customer_id is {customer_id}. My message is: 'hi'"
                else:
                    user_message_content = f"{SYSTEM_PROMPT}\n\nMy customer_id is {customer_id}. My message is: '{message}'"
            else:
                # Continuing conversation - use actual message
                user_message_content = message
                logger.info(f"Continuing conversation for customer {customer_id} with message: {message[:50]}")
            
            # Create user message
            user_message = HumanMessage(content=user_message_content)
            
            # Invoke the graph
            # For LangGraph 0.0.48, ainvoke should properly handle message appending
            response = await app_graph.ainvoke(
                {"messages": [user_message]}, 
                config=config
            )
            
            # Extract AI reply
            if response and response.get("messages"):
                last_message = response["messages"][-1]
                # Extract content from the last message
                if hasattr(last_message, 'content'):
                    ai_reply = last_message.content
                    # If content is a dict/list (structured response), extract the text
                    if isinstance(ai_reply, list) and len(ai_reply) > 0:
                        # Handle list of content blocks
                        text_parts = []
                        for block in ai_reply:
                            if isinstance(block, dict) and 'text' in block:
                                text_parts.append(block['text'])
                            elif isinstance(block, str):
                                text_parts.append(block)
                        ai_reply = '\n'.join(text_parts) if text_parts else str(ai_reply)
                    elif isinstance(ai_reply, dict) and 'text' in ai_reply:
                        ai_reply = ai_reply['text']
                    elif isinstance(ai_reply, str):
                        # Already a string, use as is
                        pass
                    else:
                        ai_reply = str(ai_reply)
                else:
                    ai_reply = str(last_message)
                
                logger.info(f"LangGraph: Final reply to {customer_id}: {ai_reply[:100]}...")
                return {"reply": ai_reply}
            else:
                raise ValueError("No response from LangGraph")
            
        except AssertionError as e:
            # === AUTO-FIX for timestamp error ===
            logger.warning(f"AssertionError for {customer_id}: {e}. Auto-resetting conversation. Please send your message again.")
            
            # Properly clear MemorySaver state for this thread (LangGraph 0.0.48 compatible)
            try:
                cleared = False
                if memory_saver:
                    # Try _storage (private attribute)
                    if hasattr(memory_saver, '_storage') and isinstance(memory_saver._storage, dict):
                        if customer_id in memory_saver._storage:
                            del memory_saver._storage[customer_id]
                            cleared = True
                    # Try storage (alternative attribute name)
                    elif hasattr(memory_saver, 'storage') and isinstance(memory_saver.storage, dict):
                        if customer_id in memory_saver.storage:
                            del memory_saver.storage[customer_id]
                            cleared = True
                    
                    if cleared:
                        logger.info(f"Cleared MemorySaver state for {customer_id}")
            except Exception as reset_err:
                logger.error(f"Error clearing memory: {reset_err}")
            
            # We do NOT retry the call. We just tell the user to try again.
            # The memory is now clear for their *next* message.
            return {"reply": "A small hiccup occurred. Please send your last message again to continue."}
            
        except Exception as e:
            logger.error(f"Error in LangGraph chat for {customer_id}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")

# --- Run the App ---
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)

