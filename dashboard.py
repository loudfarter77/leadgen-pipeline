import os
import argparse
import anthropic
import gspread
from google.oauth2.service_account import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from email.mime.text import MIMEText
import base64
import pickle
from dotenv import load_dotenv
from datetime import date
import streamlit as st
import pandas as pd

load_dotenv()

# ── Auth ──────────────────────────────────────────────────────────────────────

SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

sheets_creds = Credentials.from_service_account_file("service_account.json", scopes=SHEETS_SCOPES)
gc = gspread.authorize(sheets_creds)

gmail_creds = None
if os.path.exists("token_gmail.pkl"):
    with open("token_gmail.pkl", "rb") as token:
        gmail_creds = pickle.load(token)

if not gmail_creds or not gmail_creds.valid:
    if gmail_creds and gmail_creds.expired and gmail_creds.refresh_token:
        gmail_creds.refresh(Request())
    else:
        flow = InstalledAppFlow.from_client_secrets_file("credentials.json", GMAIL_SCOPES)
        gmail_creds = flow.run_local_server(port=0)
    with open("token_gmail.pkl", "wb") as token:
        pickle.dump(gmail_creds, token)

gmail = build("gmail", "v1", credentials=gmail_creds)
claude = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
SENDER_EMAIL = os.getenv("SENDER_EMAIL")

# ── Config ────────────────────────────────────────────────────────────────────

SHEET_ID = "1Y6DhYJqf4Sloa3WQxyLa5d8ER6rM582vsr_Tqc0BSO0"
SENDER_EMAIL = os.getenv("SENDER_EMAIL")

# ── Core functions (same as p6_outreach.py) ───────────────────────────────────

def get_prompt(lead, step):
    base = f"""You are writing a cold outreach email on behalf of an AI automation agency.

Lead details:
- Company: {lead['company_name']}
- Contact: {lead['contact_name']}
- Industry: {lead['industry']}
- Website: {lead['website']}
- Notes: {lead['notes']}

Return ONLY the email body. No subject line, no sign-off placeholder, no greeting line. Max 150 words."""

    if step == 1:
        return base + """

This is the first outreach email.
- One specific pain point relevant to their industry
- One clear value proposition around AI automation
- Soft CTA — just ask if they're open to a quick chat"""

    if step == 2:
        return base + """

This is a follow-up to an email they didn't reply to.
- Brief, friendly, no guilt
- Add one new insight or value point they haven't heard
- Soft CTA — keep it low pressure"""

    if step == 3:
        return base + """

This is the final follow-up. Last attempt.
- Short and direct
- Let them know this is the last email
- Leave the door open for the future
- No hard sell"""

def write_email_with_claude(lead, step):
    response = claude.messages.create(
        model="claude-opus-4-5",
        max_tokens=400,
        messages=[{"role": "user", "content": get_prompt(lead, step)}]
    )
    return response.content[0].text.strip()

def score_lead_with_claude(lead):
    prompt = f"""You are evaluating a sales lead for an AI automation agency that sells to small businesses.

Lead details:
- Company: {lead['company_name']}
- Industry: {lead['industry']}
- Website: {lead['website']}
- Notes: {lead['notes']}

Score this lead from 1-10 based on:
- How likely they are to need AI automation
- How reachable/approachable they seem
- How much budget they likely have

Respond in this exact format and nothing else:
SCORE: <number>
REASON: <one sentence max>"""

    response = claude.messages.create(
        model="claude-opus-4-5",
        max_tokens=100,
        messages=[{"role": "user", "content": prompt}]
    )
    text = response.content[0].text.strip()
    lines = text.split("\n")
    score = lines[0].replace("SCORE:", "").strip()
    reason = lines[1].replace("REASON:", "").strip()
    return score, reason

def send_email(to_email, contact_name, company_name, body, step):
    subjects = {
        1: f"Quick question for {company_name}",
        2: f"Following up — {company_name}",
        3: f"Last note — {company_name}",
    }
    full_body = f"Hi {contact_name},\n\n{body}\n\nBest,\nHiro"
    message = MIMEText(full_body)
    message["to"] = to_email
    message["from"] = SENDER_EMAIL
    message["subject"] = subjects[step]
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    gmail.users().messages().send(userId="me", body={"raw": raw}).execute()

def update_lead(sheet, row_index, step, new_status=None, score=None, score_reason=None):
    today = str(date.today())
    status = new_status if new_status else "active"
    sheet.update_cell(row_index, 8, status)
    sheet.update_cell(row_index, 9, step)
    sheet.update_cell(row_index, 10, today)
    sheet.update_cell(row_index, 11 + step, "TRUE")
    if score:
        sheet.update_cell(row_index, 17, score)
        sheet.update_cell(row_index, 18, score_reason)

def process_lead(sheet, all_records, lead, step):
    row_index = all_records.index(lead) + 2
    email_body = write_email_with_claude(lead, step)
    score, score_reason = score_lead_with_claude(lead)
    send_email(lead["email"], lead["contact_name"], lead["company_name"], email_body, step)
    new_status = "dead" if step == 3 else "active"
    update_lead(sheet, row_index, step, new_status, score, score_reason)
    return score, score_reason

def update_status_only(sheet, all_records, lead, new_status):
    row_index = all_records.index(lead) + 2
    sheet.update_cell(row_index, 8, new_status)

# ── Dashboard ─────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Outreach OS", page_icon="🤖", layout="wide")

st.title("🤖 Outreach OS")
st.caption("AI-powered lead gen & follow-up pipeline")

# Load data
sheet = gc.open_by_key(SHEET_ID).sheet1

def load_data():
    return sheet.get_all_records()

all_records = load_data()
df = pd.DataFrame(all_records)

# ── Stats bar ─────────────────────────────────────────────────────────────────

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Total Leads", len(df))
col2.metric("New", len(df[df["status"] == "new"]))
col3.metric("Active", len(df[df["status"] == "active"]))
col4.metric("Replied", len(df[df["status"] == "replied"]))
col5.metric("Converted", len(df[df["status"] == "converted"]))

st.divider()

# ── Bulk actions ──────────────────────────────────────────────────────────────

st.subheader("Bulk Actions")
bcol1, bcol2, bcol3 = st.columns(3)

with bcol1:
    if st.button("🚀 Send Step 1 to all NEW leads"):
        new_leads = [r for r in all_records if r["status"] == "new"]
        if not new_leads:
            st.warning("No new leads.")
        else:
            progress = st.progress(0)
            for i, lead in enumerate(new_leads):
                with st.spinner(f"Processing {lead['contact_name']}..."):
                    process_lead(sheet, all_records, lead, 1)
                progress.progress((i + 1) / len(new_leads))
            st.success(f"Sent step 1 to {len(new_leads)} leads!")
            st.rerun()

with bcol2:
    if st.button("📨 Send Step 2 to all ACTIVE (step 1) leads"):
        active_leads = [r for r in all_records if r["status"] == "active" and r["sequence_step"] == 1]
        if not active_leads:
            st.warning("No leads ready for step 2.")
        else:
            progress = st.progress(0)
            for i, lead in enumerate(active_leads):
                with st.spinner(f"Processing {lead['contact_name']}..."):
                    process_lead(sheet, all_records, lead, 2)
                progress.progress((i + 1) / len(active_leads))
            st.success(f"Sent step 2 to {len(active_leads)} leads!")
            st.rerun()

with bcol3:
    if st.button("📬 Send Step 3 to all ACTIVE (step 2) leads"):
        active_leads = [r for r in all_records if r["status"] == "active" and r["sequence_step"] == 2]
        if not active_leads:
            st.warning("No leads ready for step 3.")
        else:
            progress = st.progress(0)
            for i, lead in enumerate(active_leads):
                with st.spinner(f"Processing {lead['contact_name']}..."):
                    process_lead(sheet, all_records, lead, 3)
                progress.progress((i + 1) / len(active_leads))
            st.success(f"Sent step 3 to {len(active_leads)} leads!")
            st.rerun()

st.divider()

# ── Lead table ────────────────────────────────────────────────────────────────

st.subheader("All Leads")

status_filter = st.selectbox("Filter by status", ["all", "new", "active", "replied", "converted", "dead"])

filtered = df if status_filter == "all" else df[df["status"] == status_filter]

display_cols = ["lead_id", "company_name", "contact_name", "industry", "status", "sequence_step", "last_contacted", "score", "score_reason"]
st.dataframe(filtered[display_cols], use_container_width=True)

st.divider()

# ── Individual lead actions ───────────────────────────────────────────────────

st.subheader("Individual Lead Actions")

lead_names = [f"{r['lead_id']} — {r['contact_name']} ({r['company_name']})" for r in all_records]
selected = st.selectbox("Select a lead", lead_names)
selected_lead = all_records[lead_names.index(selected)]

st.write(f"**Status:** {selected_lead['status']} | **Step:** {selected_lead['sequence_step']} | **Score:** {selected_lead.get('score', 'N/A')}")
st.write(f"**Score reason:** {selected_lead.get('score_reason', 'N/A')}")

icol1, icol2, icol3, icol4, icol5 = st.columns(5)

with icol1:
    if st.button("Send next email"):
        next_step = int(selected_lead["sequence_step"]) + 1
        if next_step > 3:
            st.warning("Sequence complete for this lead.")
        else:
            with st.spinner("Sending..."):
                score, reason = process_lead(sheet, all_records, selected_lead, next_step)
            st.success(f"Sent step {next_step}! Score: {score}")
            st.rerun()

with icol2:
    if st.button("Mark as Replied"):
        update_status_only(sheet, all_records, selected_lead, "replied")
        st.success("Marked as replied.")
        st.rerun()

with icol3:
    if st.button("Mark as Converted"):
        update_status_only(sheet, all_records, selected_lead, "converted")
        st.success("Marked as converted.")
        st.rerun()

with icol4:
    if st.button("Mark as Dead"):
        update_status_only(sheet, all_records, selected_lead, "dead")
        st.success("Marked as dead.")
        st.rerun()

with icol5:
    if st.button("Reset to New"):
        update_status_only(sheet, all_records, selected_lead, "new")
        st.success("Reset to new.")
        st.rerun()

st.divider()

# ── Add new lead ──────────────────────────────────────────────────────────────

st.subheader("Import Leads from CSV")

with st.expander("+ Upload a CSV file"):
    st.caption("CSV must have these columns: company_name, contact_name, email, industry, website, notes")
    
    uploaded_file = st.file_uploader("Choose a CSV file", type="csv")
    
    if uploaded_file:
        import_df = pd.read_csv(uploaded_file)
        st.dataframe(import_df, use_container_width=True)
        
        if st.button("Import all leads"):
            required = ["company_name", "contact_name", "email", "industry", "website", "notes"]
            missing = [c for c in required if c not in import_df.columns]
            
            if missing:
                st.error(f"Missing columns: {', '.join(missing)}")
            else:
                existing_count = len(all_records)
                imported = 0
                for _, row in import_df.iterrows():
                    new_id = f"lead_{str(existing_count + imported + 1).zfill(3)}"
                    new_row = [
                        new_id,
                        row["company_name"],
                        row["contact_name"],
                        row["email"],
                        row.get("industry", ""),
                        row.get("website", ""),
                        row.get("notes", ""),
                        "new", 0, "", "",
                        "FALSE", "FALSE", "FALSE", "FALSE", "FALSE", "", ""
                    ]
                    sheet.append_row(new_row)
                    imported += 1
                
                st.success(f"Imported {imported} leads!")
                st.rerun()

st.divider()

# ── Webhook log ───────────────────────────────────────────────────────────────

st.subheader("Webhook Log")

webhook_leads = [r for r in all_records if "webhook" in str(r.get("notes", "")).lower() or "via webhook" in str(r.get("notes", "")).lower()]

if webhook_leads:
    webhook_df = pd.DataFrame(webhook_leads)
    display_cols = ["lead_id", "company_name", "contact_name", "email", "industry", "status", "notes"]
    st.dataframe(webhook_df[display_cols], use_container_width=True)
    st.caption(f"{len(webhook_leads)} leads received via webhook")
else:
    st.markdown("""
    <div style="background: #f8f9fa; border: 1px dashed #dee2e6; border-radius: 8px; padding: 24px; text-align: center; color: #6c757d; font-size: 13px;">
        No webhook leads yet — POST to <code>http://localhost:8000/leads</code> to see them here
    </div>
    """, unsafe_allow_html=True)

st.subheader("Add New Lead")

with st.expander("+ Add a lead manually"):
    new_id = f"lead_{str(len(all_records) + 1).zfill(3)}"
    n1, n2 = st.columns(2)
    company = n1.text_input("Company name")
    contact = n2.text_input("Contact name")
    n3, n4 = st.columns(2)
    email = n3.text_input("Email")
    industry = n4.text_input("Industry")
    n5, n6 = st.columns(2)
    website = n5.text_input("Website")
    notes = n6.text_input("Notes")

    if st.button("Add Lead"):
        if company and contact and email:
            new_row = [new_id, company, contact, email, industry, website, notes, "new", 0, "", "", "FALSE", "FALSE", "FALSE", "FALSE", "FALSE", "", ""]
            sheet.append_row(new_row)
            st.success(f"Added {contact} from {company}!")
            st.rerun()
        else:
            st.error("Company, contact and email are required.")