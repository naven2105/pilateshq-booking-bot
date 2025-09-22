# app/invoices.py
from .utils import send_whatsapp_text
from .invoices import generate_invoice_whatsapp  # reuse your existing function
import os

BASE_URL = os.getenv("BASE_URL", "https://pilateshq-booking-bot.onrender.com")

def send_invoice(wa_number: str, month_spec: str = "this month"):
    """
    Stub: Send invoice link to client.
    Wraps your existing generate_invoice_whatsapp.
    """
    message = generate_invoice_whatsapp(wa_number, month_spec, BASE_URL)
    send_whatsapp_text(wa_number, message)
