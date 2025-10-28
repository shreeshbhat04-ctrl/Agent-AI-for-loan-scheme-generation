from fastapi import FastAPI, HTTPException
import uvicorn
import httpx
from pydantic import BaseModel
import logging

# --- Configuration ---
app = FastAPI(title="Verification Agent")

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Define the URL for the mock CRM service.
# We assume this service is running on port 9001, as discussed.
CRM_SERVICE_URL = "http://127.0.0.1:9001/crm"

# --- Pydantic Models ---
class VerificationRequest(BaseModel):
    """
    This model defines the expected JSON payload for a /verify request.
    The Master Agent must send a JSON object like: {"customer_id": "101"}
    """
    customer_id: str
    # In a real scenario, you'd also pass user's "claims" here
    # e.g., claimed_name: str, claimed_phone: str

# --- API Endpoints ---
@app.post("/verify")
async def verify_kyc(request: VerificationRequest):
    """
    This endpoint verifies a customer's KYC details.
    
    1. It receives a customer_id from the Master Agent.
    2. It calls the mock CRM Service (port 9001) to get the customer's true KYC data.
    3. It returns the verification status.
    """
    customer_id = request.customer_id
    logger.info(f"Received verification request for customer_id: {customer_id}")

    # **NEW LOGIC: Call the mock CRM service**
    async with httpx.AsyncClient() as client:
        try:
            # Make the GET request to http://127.0.0.1:9001/crm/{customer_id}
            service_url = f"{CRM_SERVICE_URL}/{customer_id}"
            logger.info(f"Calling Mock CRM Service at: {service_url}")
            
            response = await client.get(service_url)
            
            # Check for HTTP errors (e.g., 404 Not Found, 500 Server Error)
            response.raise_for_status() 
            
            # If successful (HTTP 200), we get the KYC data
            kyc_data = response.json()
            logger.info(f"Successfully retrieved data from CRM: {kyc_data}")
            
            # --- Verification Logic Would Go Here ---
            # For now, just finding the customer is "verified".
            # TODO: Compare kyc_data with claims from the request
            # e.g., if request.claimed_name.lower() != kyc_data['name'].lower():
            #     return {"status": "failed", "reason": "Name mismatch"}
            # ---
            
            return {
                "status": "verified",
                "message": f"KYC data retrieved successfully for {kyc_data.get('name')}.",
                "kyc_details": kyc_data 
                # Sending the data back is useful for the Master Agent
            }

        except httpx.HTTPStatusError as exc:
            # This catches 4xx and 5xx errors from the CRM service
            if exc.response.status_code == 404:
                logger.warning(f"Customer not found in CRM (ID: {customer_id})")
                return {"status": "failed", "reason": f"Customer not found in CRM (ID: {customer_id})"}
            else:
                # Handle other potential HTTP errors (e.g., 500)
                logger.error(f"CRM service returned an error: {exc}")
                raise HTTPException(status_code=502, detail=f"CRM service error: {exc.response.status_code}")
        
        except httpx.RequestError as exc:
            # This catches connection errors (e.g., CRM service is down)
            logger.critical(f"Could not connect to CRM service at {CRM_SERVICE_URL}. Error: {exc}")
            raise HTTPException(status_code=503, detail=f"Could not connect to CRM service. Is it running on port 9001?")

# --- Main execution ---
if __name__ == "__main__":
    """
    This agent runs on port 8002.
    """
    logger.info("Starting Verification Agent on port 8002")
    uvicorn.run(app, host="127.0.0.1", port=8002)
