# app/invoices.py
"""
invoices.py
───────────────────────────────────────────────
Generates detailed WhatsApp invoices and PDFs for clients.
Pulls real booking data from the database using crud.py.
"""

import os
from io import BytesIO
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from . import crud
from .utils import send_whatsapp_text

BASE_URL = os.getenv("BASE_URL", "https://pilateshq-booking-bot.onrender.com")

# ──────────────────────────────────────────────
# PDF GENERATOR
# ──────────────────────────────────────────────
def generate_invoice_pdf(client: str, month_spec: str = "this month") -> bytes:
    """
    Generate a simple invoice PDF summarising the client’s sessions and charges.
    """
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    p.setFont("Helvetica-Bold", 16)
    p.drawString(50, height - 50, f"PilatesHQ Invoice — {client}")
    p.setFont("Helvetica", 12)
    p.drawString(50, height - 80, f"Period: {month_spec}")

    # Dummy total for PDF fallback
    p.drawString(50, height - 110, "For detailed summary, please view your WhatsApp invoice.")
    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer.read()


# ──────────────────────────────────────────────
# WHATSAPP INVOICE GENERATOR
# ──────────────────────────────────────────────
def generate_invoice_whatsapp(client_name: str, month_spec: str, base_url: str, client_id: int | None = None) -> str:
    """
    Build WhatsApp-friendly invoice message including:
    - All session dates & types
    - Price per session
    - Total
    - Banking details
    """
    # Parse month/year from month_spec if possible
    today = datetime.now()
    year = today.year
    month = today.month
    if "sep" in month_spec.lower():
        month = 9
    elif "oct" in month_spec.lower():
        month = 10
    elif "nov" in month_spec.lower():
        month = 11
    elif "dec" in month_spec.lower():
        month = 12

    # ── Fetch session data from DB
    sessions = []
    total = 0
    if client_id:
        sessions = crud.get_client_sessions_for_month(client_id, year, month)

        for s in sessions:
            price = crud.get_session_price(s["type"])
            s["price"] = price
            total += price

    # ── Build session summary
    if sessions:
        session_lines = []
        for s in sessions:
            session_lines.append(
                f"• {s['date']} at {s['time']} — {s['type'].capitalize()} (R{s['price']})"
            )
        session_text = "\n".join(session_lines)
    else:
        session_text = "No confirmed sessions found this month."

    total_text = f"💰 *Total Due: R{total}*"
    pdf_link = f"{base_url}/diag/invoice-pdf?client={client_name.replace(' ', '%20')}&month={month_spec.replace(' ', '%20')}"

    # ── Compose WhatsApp invoice message
    return (
        f"📑 *PilatesHQ Invoice — {client_name}*\n"
        f"📅 Period: {month_spec.capitalize()}\n\n"
        f"{session_text}\n\n"
        f"{total_text}\n\n"
        "🏦 *Banking Details:*\n"
        "Pilates HQ Pty Ltd\n"
        "Absa Bank — Current Account\n"
        "Account No: 4117151887\n"
        "Reference: Your Name\n\n"
        "📲 Please send Proof of Payment once done.\n"
        f"🔗 *Download PDF Invoice:* {pdf_link}"
    )


# ──────────────────────────────────────────────
# SEND INVOICE VIA WHATSAPP
# ──────────────────────────────────────────────
def send_invoice(wa_number: str, client_id: int, client_name: str, month_spec: str = "this month"):
    """
    Send invoice message to client via WhatsApp.
    """
    message = generate_invoice_whatsapp(client_name, month_spec, BASE_URL, client_id)
    send_whatsapp_text(wa_number, message)
