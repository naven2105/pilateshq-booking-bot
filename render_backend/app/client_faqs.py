#render_backend_app/client_faqs.py
"""
client_faqs.py
──────────────────────────────────────────
WhatsApp interactive FAQ menu for PilatesHQ clients.
Triggered when user types 'faq', 'faqs', or 'help'.
Includes 'Back to Menu' button for easy navigation.
"""

import re
from .utils import send_whatsapp_text, send_whatsapp_interactive

FAQ_KEYWORDS = ["faq", "faqs", "help", "questions"]

BACK_BUTTON = [{"id": "faq_menu", "title": "🔙 Back to Menu"}]

FAQ_ANSWERS = {
    "faq_bookings": (
        "🗓 *Bookings*\n"
        "You can book via WhatsApp by sending a message like:\n"
        "👉 'Book tomorrow 08h00 single'\n"
        "To cancel, message 'Cancel Tuesday 08h00'.\n"
        "Please give at least 6 hours’ notice for cancellations 🙏."
    ),
    "faq_payments": (
        "💰 *Payments*\n"
        "Reformer Rates:\n"
        "Single = R300 | Duo = R250 | Group = R180\n"
        "Bank: Absa | Account: 4117151887 | Ref: Your Name\n"
        "Invoices are automatically sent monthly via WhatsApp 📑."
    ),
    "faq_classes": (
        "🤸 *Classes*\n"
        "All sessions are 55 minutes. Bring a towel and grip socks.\n"
        "Reformer sessions focus on strength, balance, posture, and rehab support."
    ),
    "faq_studio": (
        "🏠 *Studio Info*\n"
        "Address: 71 Grant Avenue, Norwood\n"
        "Adequate Parking at the Spar 🚗\n"
        "Hours: Mon–Fri 07h30–18h00 | Sat 07h30–12h00 | Sun 07h30–12h00"
    ),
}


def handle_faq_message(wa_number: str, message: str):
    """Trigger FAQ menu if keyword detected."""
    lower_msg = message.lower().strip()
    if any(k in lower_msg for k in FAQ_KEYWORDS):
        _send_faq_menu(wa_number)
        return True
    return False


def _send_faq_menu(wa_number: str):
    """Send WhatsApp interactive FAQ menu with buttons."""
    body_text = (
        "💬 *PilatesHQ FAQs*\n"
        "Select a topic below:"
    )
    buttons = [
        {"id": "faq_bookings", "title": "Bookings 🗓"},
        {"id": "faq_payments", "title": "Payments 💰"},
        {"id": "faq_classes", "title": "Classes 🤸"},
        {"id": "faq_studio", "title": "Studio 🏠"},
    ]
    send_whatsapp_interactive(wa_number, body_text, buttons)


def handle_faq_button(wa_number: str, button_id: str):
    """Handle button click from FAQ interactive message."""
    if button_id == "faq_menu":
        _send_faq_menu(wa_number)
        return True

    if button_id in FAQ_ANSWERS:
        # Send answer with a 'Back to Menu' button
        send_whatsapp_interactive(
            wa_number,
            FAQ_ANSWERS[button_id],
            BACK_BUTTON
        )
        return True

    return False
