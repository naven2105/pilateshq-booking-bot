"""
admin_invoices.py
─────────────────
Admin-facing invoice & balance management.
"""

import logging
from datetime import datetime, timedelta
from sqlalchemy import text
from .db import get_session
from .utils import send_whatsapp_text, safe_execute, normalize_wa

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


def _find_client(name: str):
    """Look up client by name → (id, wa_number)."""
    with get_session() as s:
        row = s.execute(
            text("SELECT id, wa_number FROM clients WHERE lower(name)=lower(:n)"),
            {"n": name},
        ).first()
        if row:
            return row[0], normalize_wa(row[1])
    return None, None


# ───────────────────────────────────────────────
# Admin invoice actions
# ───────────────────────────────────────────────
def send_invoice_admin(admin_wa: str, client_name: str, month: str | None = None):
    """Admin requests invoice for a client → PDF link returned to admin."""
    cid, wa = _find_client(client_name)
    if not cid:
        safe_execute(
            send_whatsapp_text,
            admin_wa,
            f"⚠ No client found named '{client_name}'.",
            label="admin_invoice_fail",
        )
        return

    label, key = _normalize_month(month)

    with get_session() as s:
        row = s.execute(
            text(
                "SELECT COUNT(*) FROM bookings "
                "WHERE client_id=:cid AND to_char(session_date, 'YYYY-MM')=:m"
            ),
            {"cid": cid, "m": key},
        ).first()

    count = row[0] if row else 0

    if count == 0:
        msg = (
            f"💜 PilatesHQ — Invoice for {client_name} ({label})\n"
            f"No sessions booked in this period."
        )
        safe_execute(send_whatsapp_text, admin_wa, msg, label="admin_invoice_empty")
        return

    # Generate the hidden PDF URL
    pdf_url = (
        f"https://pilateshq-booking-bot.onrender.com/diag/invoice-pdf"
        f"?client={wa}&month={label.replace(' ', '%20')}"
    )

    msg = (
        f"📑 Invoice for {client_name} — {label}\n\n"
        f"🔗 Download PDF: {pdf_url}"
    )
    safe_execute(send_whatsapp_text, admin_wa, msg, label="admin_invoice_ok")


def show_balance_admin(admin_wa: str, client_name: str):
    """Admin requests balance for a client."""
    cid, wa = _find_client(client_name)
    if not cid:
        safe_execute(
            send_whatsapp_text,
            admin_wa,
            f"⚠ No client found named '{client_name}'.",
            label="admin_balance_fail",
        )
        return

    with get_session() as s:
        row = s.execute(
            text("SELECT balance FROM clients WHERE id=:cid"),
            {"cid": cid},
        ).first()

    if not row:
        safe_execute(
            send_whatsapp_text,
            admin_wa,
            f"⚠ Could not retrieve balance for {client_name}.",
            label="admin_balance_fail",
        )
        return

    bal = row[0]
    safe_execute(
        send_whatsapp_text,
        admin_wa,
        f"💜 Balance for {client_name}: {bal} sessions.",
        label="admin_balance_ok",
    )
