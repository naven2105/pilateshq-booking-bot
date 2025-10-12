#render_backend_app/client_faqs.py
"""
client_faqs.py
──────────────────────────────────────────
WhatsApp interactive FAQ menu for PilatesHQ clients.
Triggered when user types 'faq', 'faqs', or 'help'.
Includes "Back to FAQs" button for navigation and
falls back to static FAQ text if interactive mode fails.
"""

import re
from .utils import send_whatsapp_text, send_whatsapp_interactive
from .faqs import build_faq_text  # fallback

# ── Constants ────────────────────────────────────────────────
FAQ_KEYWORDS = ["faq", "faqs", "help", "questions"]
BACK_BUTTON = [{"id": "faq_menu", "title": "🔙 Back to FAQs"}]

# ── FAQ Topics ────────────────────────────────────────────────
FAQ_ANSWERS = {
    "faq_bookings": (
        "🗓 *Bookings*\n"
        "You can book via WhatsApp by sending:\n"
        "👉 'Book tomorrow 08h00 single'\n"
        "To cancel, message 'Cancel Tuesday 08h00'.\n\n"
        "Please give at least *6 hours’ notice* for cancellations 🙏."
    ),
    "faq_reschedule": (
        "🔁 *Rescheduling & Packages*\n"
        "If you can’t make your session, just message 'Reschedule' and Nadine will assist.\n\n"
        "💼 *Packages:*\n"
        "• Packages are valid for 30 days from first use.\n"
        "• Unused sessions cannot roll over unless arranged.\n"
        "• You’ll receive a reminder when your balance is low."
    ),
    "faq_payments": (
        "💰 *Payments*\n"
        "Rates per session:\n"
        "• Single = R300\n"
        "• Duo = R250 per person\n"
        "• Group = R180 per person\n\n"
        "💳 *Banking Details:*\n"
        "PilatesHQ Pty Ltd\n"
        "Absa Bank — Current Account\n"
        "Account No: 4117151887\n"
        "Reference: Your Name\n\n"
        "Invoices are sent monthly via WhatsApp 📑."
    ),
    "faq_classes": (
        "🤸 *Classes*\n"
        "All sessions are 55 minutes and use a range of Pilates equipment.\n"
        "Please bring a towel and grip socks.\n\n"
        "Sessions focus on strength, posture, mobility, and rehab support."
    ),
    "faq_studio": (
        "🏠 *Studio Info*\n"
        "📍 71 Grant Avenue, Norwood, Johannesburg\n"
        "🚗 Parking: Available near Spar\n"
        "🕒 Hours:\n"
        "   • Mon–Fri: 06h00–18h00\n"
        "   • Sat: 08h00–10h00\n"
        "   • Sun: Closed"
    ),
}

# ── Entrypoints ───────────────────────────────────────────────
def handle_faq_message(wa_number: str, message: str):
    """Trigger FAQ menu when a keyword is detected."""
    lower_msg = message.lower().strip()
    if any(k in lower_msg for k in FAQ_KEYWORDS):
        _send_faq_menu(wa_number)
        return True
    return False


def _send_faq_menu(wa_number: str):
    """Send WhatsApp interactive FAQ menu with graceful fallback."""
    body_text = (
        "💜 *Welcome to PilatesHQ FAQs!*\n"
        "Choose a topic below to learn more 👇"
    )
    buttons = [
        {"id": "faq_bookings", "title": "🗓 Bookings"},
        {"id": "faq_reschedule", "title": "🔁 Rescheduling / Packages"},
        {"id": "faq_payments", "title": "💰 Payments"},
        {"id": "faq_classes", "title": "🤸 Classes"},
        {"id": "faq_studio", "title": "🏠 Studio Info"},
    ]
    try:
        send_whatsapp_interactive(wa_number, body_text, buttons)
    except Exception as e:
        print(f"[FAQ] Interactive menu failed ({e}); sending fallback text.")
        send_whatsapp_text(wa_number, build_faq_text())


def handle_faq_button(wa_number: str, button_id: str):
    """Handle button click from FAQ interactive message."""
    if button_id == "faq_menu":
        _send_faq_menu(wa_number)
        return True

    if button_id in FAQ_ANSWERS:
        send_whatsapp_interactive(
            wa_number,
            FAQ_ANSWERS[button_id] + "\n\n💬 Reply *FAQ* to reopen the menu.",
            BACK_BUTTON
        )
        return True

    return False
