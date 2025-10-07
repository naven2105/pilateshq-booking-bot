# app/invoices.py
import os
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from .utils import send_whatsapp_text

BASE_URL = os.getenv("BASE_URL", "https://pilateshq-booking-bot.onrender.com")


# ── PDF Generator ─────────────────────────────────────────────
def generate_invoice_pdf(client: str, month_spec: str = "this month") -> bytes:
    """
    Generate a simple invoice PDF.
    Replace with real DB-driven invoice content.
    """
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    p.setFont("Helvetica-Bold", 16)
    p.drawString(50, height - 50, f"PilatesHQ Invoice — {client}")
    p.setFont("Helvetica", 12)
    p.drawString(50, height - 80, f"Period: {month_spec}")
    p.drawString(50, height - 110, "No sessions booked this period. We miss you! 💜")

    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer.read()


# ── WhatsApp Message Generator ─────────────────────────────
def generate_invoice_whatsapp(client: str, month_spec: str, base_url: str) -> str:
    """
    Generate WhatsApp-friendly invoice text + PDF link.
    """
    return (
        f"📑 PilatesHQ Invoice — {client}\n"
        f"Period: {month_spec.capitalize()}\n\n"
        "Banking details:\n"
        "Pilates HQ Pty Ltd\n"
        "Absa Bank\n"
        "Current Account\n"
        "Account No: 41171518 87\n\n"
        "Notes:\n"
        "• Use your name as reference\n"
        "• Send POP once paid\n\n"
        f"🔗 Download full invoice (PDF): "
        f"{base_url}/diag/invoice-pdf?client={client}&month={month_spec.replace(' ', '%20')}"
    )


# ── Wrapper for Router ─────────────────────────────────────
def send_invoice(wa_number: str, month_spec: str = "this month"):
    """
    Send invoice link/message to a client over WhatsApp.
    """
    message = generate_invoice_whatsapp(wa_number, month_spec, BASE_URL)
    send_whatsapp_text(wa_number, message)
