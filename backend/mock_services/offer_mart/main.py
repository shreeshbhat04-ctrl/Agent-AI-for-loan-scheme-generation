import json
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List

app = FastAPI()

# Load the dummy data
with open("../../db/synthetic_data.json", "r") as f:
    customers = json.load(f)

class LoanOffer(BaseModel):
    cust_id: str
    pre_approved_limit: int
    interest_options: List[str]

@app.get("/offers", response_model=LoanOffer)
def get_offers(cust_id: str):
    """
    Simulates the Offer-Mart API endpoint.
    """
    for customer in customers:
        if customer["cust_id"] == cust_id:
            return LoanOffer(
                cust_id=customer["cust_id"],
                pre_approved_limit=customer["pre_approved_limit"],
                interest_options=customer["interest_options"]
            )
    raise HTTPException(status_code=404, detail="Customer not found")

# To run this service:
# cd backend/mock_services/offer_mart
# uvicorn offer_service:app --port 9003