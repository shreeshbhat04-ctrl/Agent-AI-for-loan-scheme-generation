# Run all loan agents + master agent in separate PowerShell windows

$BASE_PATH = Get-Location
$VENV_PATH = "$BASE_PATH\venv\Scripts\Activate.ps1"

# Activate virtual environment (in each window)
function Start-Agent {
    param([string]$AgentPath, [int]$Port)
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd $AgentPath; & '$VENV_PATH'; uvicorn main:app --reload --port $Port"
}

Write-Host "Starting all agents..."

# Master Agent
Start-Agent "$BASE_PATH\master_agent" 8000

# Sales Agent
Start-Agent "$BASE_PATH\agents\sales_agent" 8001

# Verification Agent
Start-Agent "$BASE_PATH\agents\verification_agent" 8002

# Underwriting Agent
Start-Agent "$BASE_PATH\agents\underwriting_agent" 8003

# Sanction Agent
Start-Agent "$BASE_PATH\agents\sanction_generator" 8004
#crm
Start-Agent "$BASE_PATH\mock_services\crm" 9001
#credit
Start-Agent "$BASE_PATH\mock_services\credit_bureau" 9002
#offer
Start-Agent "$BASE_PATH\mock_services\offer_mart" 9003

Write-Host "`n✅ All agents are starting in separate PowerShell windows!"
