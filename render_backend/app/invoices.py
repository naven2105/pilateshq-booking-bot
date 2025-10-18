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
def generate_invoice_pdf(client: str, wa_number: str, month_spec: str = "this month") -> bytes:
    """
    Generate a simple invoice PDF summarising the client’s sessions and charges.
    Displays mobile number in header (for admin verification).
    """
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    p.setFont("Helvetica-Bold", 16)
    p.drawString(50, height - 50, f"PilatesHQ Invoice — {client}")
    p.setFont("Helvetica", 12)
    p.drawString(50, height - 75, f"Period: {month_spec}")
    p.drawString(50, height - 95, f"Mobile: {wa_number}")

    p.drawString(50, height - 130, "For detailed summary, please view your WhatsApp invoice.")
    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer.read()


# ──────────────────────────────────────────────
# WHATSAPP INVOICE GENERATOR
# ──────────────────────────────────────────────
def generate_invoice_whatsapp(client_name: str, month_spec: str, base_url: str,
                              client_id: int | None = None, wa_number: str | None = None) -> str:
    """
    Build WhatsApp-friendly invoice message including:
    - All session dates & types
    - Price per session
    - Total
    - Banking details
    """
    today = datetime.now()
    year, month = today.year, today.month

    month_lookup = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
    }
    for key, val in month_lookup.items():
        if key in month_spec.lower():
            month = val
            break

    sessions = []
    total = 0
    if client_id:
        sessions = crud.get_client_sessions_for_month(client_id, year, month)
        for s in sessions:
            price = crud.get_session_price(s["type"])
            s["price"] = price
            total += price

    if sessions:
        session_lines = [
            f"• {s['date']} at {s['time']} — {s['type'].capitalize()} (R{s['price']})"
            for s in sessions
        ]
        session_text = "\n".join(session_lines)
    else:
        session_text = "No confirmed sessions found this month."

    total_text = f"💰 *Total Due: R{total}*"
    pdf_link = (
        f"{base_url}/diag/invoice-pdf?"
        f"client={client_name.replace(' ', '%20')}"
        f"&month={month_spec.replace(' ', '%20')}"
        f"&mobile={wa_number or ''}"
    )

    # ── Compose WhatsApp invoice message (client-friendly)
    message = (
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

    return message


# ──────────────────────────────────────────────
# SEND INVOICE VIA WHATSAPP
# ──────────────────────────────────────────────
def send_invoice(wa_number: str, client_id: int, client_name: str,
                 month_spec: str = "this month"):
    """
    Send invoice message to client via WhatsApp.
    """
    message = generate_invoice_whatsapp(client_name, month_spec, BASE_URL, client_id, wa_number)
    send_whatsapp_text(wa_number, message)
