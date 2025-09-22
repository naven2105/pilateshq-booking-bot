# app/faqs.py
from .utils import send_whatsapp_text

FAQ_TEXT = (
    "❓ *Frequently Asked Questions*\n\n"
    "1. What are your prices?\n"
    "   • Single: R300\n"
    "   • Duo: R250 pp\n"
    "   • Group: R180 pp\n\n"
    "2. Where are you located?\n"
    "   • 71 Grant Avenue, Norwood, Johannesburg\n\n"
    "3. How do I book?\n"
    "   • Reply '0' and Nadine will assist you.\n\n"
    "4. What if I need to cancel?\n"
    "   • Please let Nadine know at least 12h before your session."
)

def show_faq(wa_number: str):
    """
    Stub: Show FAQ content.
    """
    send_whatsapp_text(wa_number, FAQ_TEXT)
