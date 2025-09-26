"""
client_invoices.py
──────────────────
Handles client invoice and balance requests.
"""

import logging
from datetime import datetime, timedelta
from sqlalchemy import text
from .db import get_session
from .utils import send_whatsapp_text, send_whatsapp_buttons, safe_execute

log = logging.getLogger(__name__)


# ───────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────
def _normalize_month(month: str | None) -> tuple[str, str]:
    today = datetime.today()

    if not month or month.lower() in {"this month", "current"}:
        label = today.strftime("%B %Y")
        key = today.strftime("%Y-%m")
        return label, key

    if month.lower() == "last month":
        prev = today.replace(day=1) - timedelta(days=1)
        label = prev.strftime("%B %Y")
        key = prev.strftime("%Y-%m")
        return label, key

    try:
        dt = datetime.strptime(month, "%B %Y")
        label = dt.strftime("%B %Y")
        key = dt.strftime("%Y-%m")
        return label, key
    except Exception:
        label = today.strftime("%B %Y")
        key = today.strftime("%Y-%m")
        return label, key


# ───────────────────────────────────────────────
# Public API
# ───────────────────────────────────────────────
def send_invoice(wa_number: str, month: str | None = None):
    """Send invoice for the given month (default = this month)."""
    label, key = _normalize_month(month)

    with get_session() as s:
        row = s.execute(
            text(
                "SELECT COUNT(*) FROM bookings "
                "WHERE wa_number=:wa AND to_char(session_date, 'YYYY-MM')=:m"
            ),
            {"wa": wa_number, "m": key},
        ).first()

    count = row[0] if row else 0

    if count == 0:
        msg = (
            f"💜 PilatesHQ — {label}\n"
            f"No sessions booked this period. We miss you!\n\n"
            "Would you like to book your next class?"
        )
        safe_execute(
            send_whatsapp_buttons,
            wa_number,
            msg,
            buttons=[{"id": "book_now", "title": "📅 Book Now"}],
            label="client_invoice_empty",
        )
        return

    # Generate the hidden PDF URL
    pdf_url = (
        f"https://pilateshq-booking-bot.onrender.com/diag/invoice-pdf"
        f"?client={wa_number}&month={label.replace(' ', '%20')}"
    )

    # Show only a clean hyperlink
    msg = (
        f"📑 PilatesHQ Invoice — {label}\n\n"
        f"🔗 [Download Invoice PDF]({pdf_url})"
    )
    safe_execute(send_whatsapp_text, wa_number, msg, label="client_invoice_ok")


def show_balance(wa_number: str):
    """Show remaining prepaid sessions (if tracked)."""
    with get_session() as s:
        row = s.execute(
            text("SELECT balance FROM clients WHERE wa_number=:wa"),
            {"wa": wa_number},
        ).first()

    if not row:
        safe_execute(
            send_whatsapp_text,
            wa_number,
            "⚠ Could not retrieve your balance. Please contact Nadine.",
            label="client_balance_fail",
        )
        return

    bal = row[0]
    safe_execute(
        send_whatsapp_text,
        wa_number,
        f"💜 Your current package balance is: {bal} sessions.",
        label="client_balance_ok",
    )
