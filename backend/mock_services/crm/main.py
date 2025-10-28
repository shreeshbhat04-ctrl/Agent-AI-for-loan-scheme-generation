import json
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

# Load the dummy data
with open("../../db/synthetic_data.json", "r") as f:
    customers = json.load(f)

# Pydantic model for the response
class CustomerKYC(BaseModel):
    cust_id: str
    name: str
    phone: str
    address: str

@app.get("/crm/{cust_id}", response_model=CustomerKYC)
def get_customer_kyc(cust_id: str):
    """
    Simulates the CRM API endpoint for KYC verification.
    """
    for customer in customers:
        if customer["cust_id"] == cust_id:
            return CustomerKYC(
                cust_id=customer["cust_id"],
                name=customer["name"],
                phone=customer["phone"],
                address=customer["address"]
            )
    raise HTTPException(status_code=404, detail="Customer not found")

# To run this service:
# cd backend/mock_services/crm
# uvicorn crm_service:app --port 8001