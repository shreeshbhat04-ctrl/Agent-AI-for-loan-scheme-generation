import uvicorn
import httpx
import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from contextlib import asynccontextmanager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Configuration ---
# This is the service this agent CALLS
OFFER_MART_URL = "http://127.0.0.1:9003/offers"

# --- Pydantic Models ---
class SalesRequest(BaseModel):
    customer_id: str

class SalesResponse(BaseModel):
    agent: str
    message: str
    pre_approved_limit: int | None = None
    interest_options: list[str] | None = None

# This is the model we EXPECT from the Offer-Mart
class LoanOfferResponse(BaseModel):
    cust_id: str
    pre_approved_limit: int
    interest_options: list[str]

# --- HTTP Client ---
app_http_client = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global app_http_client
    app_http_client = httpx.AsyncClient()
    yield
    await app_http_client.close()

app = FastAPI(title="Sales Agent", lifespan=lifespan)

# --- Helper Function ---
async def call_offer_mart(customer_id: str) -> LoanOfferResponse:
    """Calls the Mock Offer-Mart service."""
    url = f"{OFFER_MART_URL}?cust_id={customer_id}"
    try:
        response = await app_http_client.get(url)
        response.raise_for_status()
        return LoanOfferResponse(**response.json())#responds with parsed JSON
    except httpx.HTTPStatusError as e:#handles HTTP errors
        logger.error(f"Offer-Mart returned {e.response.status_code} for {customer_id}")
        raise
    except httpx.RequestError as e:#handles connection errors
        logger.error(f"Could not connect to Offer-Mart: {e}")
        raise

# --- API Endpoints ---
@app.get("/")
def root():
    return {"message": "Sales Agent is live!"}

@app.post("/sales", response_model=SalesResponse)
async def handle_sales(request: SalesRequest):
    """
    Handles the initial sales conversation by fetching offers.
    """
    logger.info(f"Sales request for customer {request.customer_id}")
    try:
        # Call the Offer-Mart
        offer_data = await call_offer_mart(request.customer_id)
        
        # --- THIS IS THE FIX ---
        # We must include the offer data in our response
        # to the Master Agent.
        return SalesResponse(
            agent="Sales Agent",
            message=f"Found offer for {request.customer_id}",
            pre_approved_limit=offer_data.pre_approved_limit,
            interest_options=offer_data.interest_options
        )
        
    except (httpx.RequestError, httpx.HTTPStatusError):
        # Fallback if Offer-Mart is down or customer not found
        logger.warn(f"Failed to get offer for {request.customer_id}. Giving generic offer.")
        return SalesResponse(
            agent="Sales Agent",
            message="No specific offer found, giving generic one.",
            pre_approved_limit=25000,
            interest_options=["12.5%"]
        )

# --- Run the App ---
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8001)

