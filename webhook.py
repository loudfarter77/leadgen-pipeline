import gspread
from google.oauth2.service_account import Credentials
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, EmailStr
from dotenv import load_dotenv
import uvicorn

load_dotenv()

# ── Auth ──────────────────────────────────────────────────────────────────────

SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
sheets_creds = Credentials.from_service_account_file("service_account.json", scopes=SHEETS_SCOPES)
gc = gspread.authorize(sheets_creds)

# ── Config ────────────────────────────────────────────────────────────────────

SHEET_ID = "1Y6DhYJqf4Sloa3WQxyLa5d8ER6rM582vsr_Tqc0BSO0"

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Outreach OS Webhook")

# ── Lead model ────────────────────────────────────────────────────────────────

class Lead(BaseModel):
    company_name: str
    contact_name: str
    email: str
    industry: str = ""
    website: str = ""
    notes: str = ""

# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "Outreach OS webhook is live"}

@app.post("/leads")
def receive_lead(lead: Lead):
    try:
        sheet = gc.open_by_key(SHEET_ID).sheet1
        all_records = sheet.get_all_records()
        new_id = f"lead_{str(len(all_records) + 1).zfill(3)}"

        new_row = [
            new_id,
            lead.company_name,
            lead.contact_name,
            lead.email,
            lead.industry,
            lead.website,
            lead.notes,
            "new", 0, "", "",
            "FALSE", "FALSE", "FALSE", "FALSE", "FALSE", "", ""
        ]

        sheet.append_row(new_row)

        return {
            "success": True,
            "message": f"Lead {new_id} added successfully",
            "lead_id": new_id
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run("webhook:app", host="0.0.0.0", port=8000, reload=True)