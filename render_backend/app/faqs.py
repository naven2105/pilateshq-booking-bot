# app/faqs.py
"""
faqs.py
────────────────────────────────────────────
Static fallback text version of the PilatesHQ FAQs.
Used when the interactive WhatsApp FAQ menu fails.
Kept in sync with client_faqs.py for consistent content.
"""

from .utils import send_whatsapp_text

# ── FAQ Content ─────────────────────────────────────────────
FAQ_SECTIONS = [
    (
        "🗓 Bookings",
        "You can book via WhatsApp by sending:\n"
        "👉 'Book tomorrow 08h00 single'\n"
        "To cancel, message 'Cancel Tuesday 08h00'.\n\n"
        "Please give at least *6 hours’ notice* for cancellations 🙏."
    ),
    (
        "🔁 Rescheduling & Packages",
        "If you can’t make your session, just message 'Reschedule' and Nadine will assist.\n\n"
        "💼 *Packages:*\n"
        "• Packages are valid for 30 days from first use.\n"
        "• Unused sessions cannot roll over unless arranged.\n"
        "• You’ll receive a reminder when your balance runs low."
    ),
    (
        "💰 Payments",
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
    (
        "🤸 Classes",
        "All sessions are 55 minutes and use a range of Pilates equipment.\n"
        "Please bring a towel and grip socks.\n\n"
        "Sessions focus on strength, posture, mobility, and rehabilitation support."
    ),
    (
        "🏠 Studio Info",
        "📍 71 Grant Avenue, Norwood, Johannesburg\n"
        "🚗 Parking: Available near Spar\n"
        "🕒 Hours:\n"
        "   • Mon–Fri: 06h00–18h00\n"
        "   • Sat: 08h00–10h00\n"
        "   • Sun: Closed"
    ),
]

# ── Builders ───────────────────────────────────────────────
def build_faq_text() -> str:
    """Return a formatted plain-text FAQ message."""
    lines = [
        "💜 *PilatesHQ — Frequently Asked Questions*\n",
        "Here’s everything you might need to know 👇",
        "",
    ]
    for title, body in FAQ_SECTIONS:
        lines.append(f"{title}\n{body}\n")
    lines.append("💬 Reply *FAQ* to open the interactive menu again.")
    return "\n".join(lines)

# ── Sender ─────────────────────────────────────────────────
def show_faq(wa_number: str):
    """Send full static FAQ text."""
    send_whatsapp_text(wa_number, build_faq_text())
