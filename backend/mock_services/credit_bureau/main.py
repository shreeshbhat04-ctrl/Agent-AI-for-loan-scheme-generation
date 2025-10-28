import json
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

# Load the dummy data
with open("../../db/synthetic_data.json", "r") as f:
    customers = json.load(f)

class CreditScore(BaseModel):
    cust_id: str
    score: int

@app.get("/credit_score", response_model=CreditScore)
def get_credit_score(cust_id: str):
    """
    Simulates the Credit Bureau API endpoint.
    """
    for customer in customers:
        if customer["cust_id"] == cust_id:
            return CreditScore(
                cust_id=customer["cust_id"],
                score=customer["credit_score"]
            )
    raise HTTPException(status_code=404, detail="Customer not found")

# To run this service:
# cd backend/mock_services/credit_bureau
# uvicorn bureau_service:app --port 9002