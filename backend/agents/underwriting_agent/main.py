import uvicorn
import httpx
import logging
import math  # NEW: We need this for the EMI calculation
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from contextlib import asynccontextmanager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Configuration ---
# This is the service this agent CALLS
CREDIT_BUREAU_URL = "http://127.0.0.1:9002/credit_score"

# --- NEW: Expanded Request Model ---
# The Master Agent MUST send all of this
class UnderwriteRequest(BaseModel):
    customer_id: str
    requested_loan_amount: int
    pre_approved_limit: int  # We need this to check the 1x/2x rules
    monthly_salary: int      # We need this for the EMI check
    interest_rate: float     # Annual interest rate (e.g., 8.5)
    loan_tenure_months: int  # e.g., 36

# This is the model we EXPECT from the Credit Bureau
class CreditScoreResponse(BaseModel):
    cust_id: str
    score: int

# --- NEW: EMI Calculation Function ---
def calculate_emi(p: int, r_annual: float, n_months: int) -> float:
    """
    Calculates the Equated Monthly Installment (EMI).
    P = Principal loan amount
    r_annual = Annual interest rate
    n_months = Number of months
    """
    if n_months <= 0 or r_annual < 0:
        return 0.0
    
    # Convert annual rate to monthly rate
    r_monthly = r_annual / (12 * 100)
    
    # Handle 0% interest rate
    if r_monthly == 0:
        return p / n_months
        
    # EMI formula: P * r * (1+r)^n / ((1+r)^n - 1)
    try:
        numerator = p * r_monthly * math.pow(1 + r_monthly, n_months)
        denominator = math.pow(1 + r_monthly, n_months) - 1
        emi = numerator / denominator
        return emi
    except (OverflowError, ZeroDivisionError):
        return float('inf')


# --- HTTP Client ---
app_http_client = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global app_http_client
    app_http_client = httpx.AsyncClient()
    yield
    await app_http_client.close()

app = FastAPI(title="Underwriting Agent", lifespan=lifespan)

# --- Helper Function ---
async def call_credit_bureau(customer_id: str) -> CreditScoreResponse:
    """Calls the Mock Credit Bureau service."""
    url = f"{CREDIT_BUREAU_URL}?cust_id={customer_id}"
    try:
        response = await app_http_client.get(url)
        response.raise_for_status()
        return CreditScoreResponse(**response.json())
    except httpx.HTTPStatusError as e:
        logger.error(f"Credit Bureau returned {e.response.status_code} for {customer_id}")
        raise
    except httpx.RequestError as e:
        logger.error(f"Could not connect to Credit Bureau: {e}")
        raise

# --- API Endpoints ---
@app.get("/")
def root():
    return {"message": "Underwriting Agent is live!"}

@app.post("/underwrite")
async def underwrite(request: UnderwriteRequest):
    """
    Performs underwriting using the full PDF logic:
    1. Checks credit score.
    2. Checks 1x pre-approved limit.
    3. Checks 2x pre-approved limit + EMI 50% salary rule.
    """
    logger.info(f"Underwriting request for {request.customer_id} for ₹{request.requested_loan_amount}")

    # --- Rule 0: Get Credit Score ---
    try:
        score_data = await call_credit_bureau(request.customer_id)
        credit_score = score_data.score
        logger.info(f"Customer {request.customer_id} score is {credit_score}")
        
        if credit_score < 700:
            logger.warn(f"REJECTED: Customer {request.customer_id} score ({credit_score}) is below 700.")
            return {"status": "rejected", "reason": "Credit score is below the 700 minimum."}
    
    except (httpx.RequestError, httpx.HTTPStatusError):
        logger.error(f"Could not fetch credit score for {request.customer_id}.")
        raise HTTPException(status_code=503, detail="Could not connect to Credit Bureau.")

    # --- PDF Business Logic ---
    p = request.requested_loan_amount
    limit = request.pre_approved_limit
    salary = request.monthly_salary

    # --- Rule 1: <= Pre-approved limit ---
    if p <= limit:
        logger.info(f"APPROVED: {p} is within pre-approved limit of {limit}.")
        return {"status": "approved", "reason": "Amount is within pre-approved limit."}

    # --- Rule 2: > 2x Pre-approved limit ---
    if p > (2 * limit):
        logger.warn(f"REJECTED: {p} is > 2x pre-approved limit of {limit}.")
        return {"status": "rejected", "reason": f"Requested amount (₹{p}) is more than 2x your pre-approved limit (₹{limit})."}

    # --- Rule 3: Between 1x and 2x limit (EMI Check) ---
    if limit < p <= (2 * limit):
        logger.info(f"Amount {p} is > 1x limit, checking EMI against salary {salary}...")
        
        # Check for placeholder salary (if user was on easy path)
        if salary <= 0:
            logger.warn(f"REJECTED: Salary check required but no salary provided.")
            return {"status": "rejected", "reason": "Salary verification is required for this amount."}

        emi = calculate_emi(p, request.interest_rate, request.loan_tenure_months)
        max_allowed_emi = salary * 0.50
        
        logger.info(f"Calculated EMI: ₹{emi:.2f}. Max allowed EMI (50% salary): ₹{max_allowed_emi:.2f}")

        if emi <= max_allowed_emi:
            logger.info(f"APPROVED: EMI (₹{emi:.2f}) is within 50% of salary.")
            return {"status": "approved", "reason": "Approved based on income verification."}
        else:
            logger.warn(f"REJECTED: EMI (₹{emi:.2f}) exceeds 50% of salary (₹{max_allowed_emi:.2f}).")
            return {"status": "rejected", "reason": f"Your EMI (₹{emi:.2f}/mo) would exceed 50% of your monthly salary."}

    # Fallback (shouldn't be reached)
    return {"status": "rejected", "reason": "Invalid loan parameters."}

# --- Run the App ---
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8003)

