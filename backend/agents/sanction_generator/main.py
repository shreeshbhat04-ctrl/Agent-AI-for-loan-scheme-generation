import uvicorn
import httpx
import logging
import datetime
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from contextlib import asynccontextmanager
from fpdf import FPDF

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Configuration ---
CRM_SERVICE_URL = "http://127.0.0.1:9001/crm"
# We go up TWO levels (../..) to get from /agents/sanction_generator/ to /backend/
OUTPUT_DIR = "../../sanction_letters/" 

# --- Pydantic Models ---
class SanctionRequest(BaseModel):
    customer_id: str
    loan_amount: int
    interest_rate: float
    tenure_months: int

class CustomerKYC(BaseModel):
    cust_id: str
    name: str
    phone: str
    address: str

# --- HTTP Client ---
app_http_client = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global app_http_client
    app_http_client = httpx.AsyncClient()
    yield
    await app_http_client.close()

# --- THIS IS THE FIX ---
# The parameter is 'lifespan', not 'lifspan'
app = FastAPI(title="Sanction Letter Generator", lifespan=lifespan)
# --- END OF FIX ---


# --- PDF Generation Class ---
class PDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 15)
        self.cell(0, 10, "Loan Sanction Letter", 1, 0, "C")
        self.ln(20)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.cell(0, 10, f"Page {self.page_no()}", 0, 0, "C")

    def customer_details(self, name: str, address: str, phone: str):
        self.set_font("Helvetica", "B", 12)
        self.cell(0, 10, f"Date: {datetime.date.today().strftime('%d-%b-%Y')}", 0, 1)
        self.ln(5)
        self.cell(0, 10, "To,", 0, 1)
        self.cell(0, 10, name, 0, 1)
        self.cell(0, 10, address, 0, 1)
        self.cell(0, 10, f"Phone: {phone}", 0, 1)
        self.ln(10)

    def loan_body(self, amount: int, rate: float, tenure: int):
        self.set_font("Helvetica", "", 12)
        self.cell(0, 10, "Subject: Sanction of Personal Loan", 0, 1)
        self.ln(10)
        self.multi_cell(0, 10, 
            f"Dear Sir/Madam,\n\n"
            f"We are pleased to inform you that your personal loan has been sanctioned. "
            f"The details of the sanction are as follows:\n")
        self.ln(10)
        self.set_font("Helvetica", "B", 12)
        self.cell(95, 10, "Loan Amount", 1)
        self.cell(95, 10, f"Rs. {amount:,}", 1, 1)
        self.cell(95, 10, "Annual Interest Rate", 1)
        self.cell(95, 10, f"{rate:.2f} %", 1, 1)
        self.cell(95, 10, "Loan Tenure", 1)
        self.cell(95, 10, f"{tenure} months", 1, 1)
        self.ln(10)
        self.set_font("Helvetica", "", 12)
        self.multi_cell(0, 10, "This offer is valid for 7 days. We look forward to our association with you.\n\nSincerely,\nYour Loan Team")


# --- Helper Function ---
async def get_customer_details(customer_id: str) -> CustomerKYC:
    """Calls the Mock CRM service to get name and address."""
    url = f"{CRM_SERVICE_URL}/{customer_id}"
    try:
        response = await app_http_client.get(url)
        response.raise_for_status()
        return CustomerKYC(**response.json())
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        logger.error(f"Could not get customer details from CRM: {e}")
        raise HTTPException(status_code=503, detail="Could not connect to CRM service for details.")


# --- API Endpoint ---
@app.post("/sanction")
async def generate_sanction_letter(request: SanctionRequest):
    logger.info(f"Sanction request received for {request.customer_id}")
    
    # 1. Get customer details from CRM
    try:
        customer = await get_customer_details(request.customer_id)
    except HTTPException as e:
        return {"status": "failed", "reason": e.detail} # This will now be a 503

    # 2. Generate the PDF
    try:
        pdf = PDF()
        pdf.add_page()
        pdf.customer_details(customer.name, customer.address, customer.phone)
        pdf.loan_body(request.loan_amount, request.interest_rate, request.tenure_months)
        
        # 3. Save the PDF to the folder
        # This path will now correctly be: backend/sanction_letters/loan_sanction_101.pdf
        file_path = f"{OUTPUT_DIR}loan_sanction_{request.customer_id}.pdf"
        pdf.output(file_path)
        
        logger.info(f"Successfully generated PDF: {file_path}")
        
        # 4. Return a JSON success message to the Master Agent
        return {
            "status": "success",
            "message": f"Sanction letter has been generated successfully and saved!",
            "file_path": file_path
        }
    except Exception as e:
        logger.error(f"Failed to generate PDF: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate PDF letter.")

# --- Run the App ---
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8004)

