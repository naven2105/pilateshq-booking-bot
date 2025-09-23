# app/admin_nudge.py
"""
Handles all admin-facing nudges (messages to Nadine).
Centralises notifications for leads, client requests, cancellations, etc.
"""

from datetime import datetime
import logging
from sqlalchemy import text
from .db import get_session
from .utils import send_whatsapp_text, normalize_wa
from .config import NADINE_WA


def notify_admin_new_lead(name: str, wa: str):
    """Notify Nadine of a new prospect lead."""
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    msg = (
        "📥 *New Prospect Lead*\n"
        f"• Name: {name}\n"
        f"• WhatsApp: {wa}\n"
        f"• Received: {ts}\n\n"
        "👉 To convert: reply `convert {wa}`\n"
        "👉 Or add with number: `add John with number 0821234567`"
    )
    _send_to_admin(msg)


def notify_client_contact_request(name: str, wa: str):
    """Client pressed 'contact Nadine' or typed 'Nadine'."""
    msg = f"📞 Client requested contact: {name} ({wa})"
    _send_to_admin(msg)


def notify_client_message(name: str, wa: str, text_in: str):
    """Forward free-form client messages to Nadine."""
    msg = (
        f"📩 *Client message*\n"
        f"👤 {name} ({wa})\n"
        f"💬 \"{text_in}\""
    )
    _send_to_admin(msg)


# ── Placeholders for future nudges ──────────────────────
def notify_no_show(name: str, wa: str):
    msg = f"🚫 No-show detected for {name} ({wa})."
    _send_to_admin(msg)


def notify_sick(name: str, wa: str):
    msg = f"🤒 {name} ({wa}) reported sick today."
    _send_to_admin(msg)


def notify_cancellation(name: str, wa: str):
    msg = f"❌ {name} ({wa}) cancelled a session."
    _send_to_admin(msg)


# ── Shared helper ───────────────────────────────────────
def _send_to_admin(msg: str):
    """Send WhatsApp message to Nadine and log it."""
    try:
        if NADINE_WA:
            send_whatsapp_text(normalize_wa(NADINE_WA), msg)

        with get_session() as s:
            s.execute(
                text(
                    "INSERT INTO notifications_log (client_id, message, created_at) "
                    "VALUES (NULL, :msg, now())"
                ),
                {"msg": msg},
            )
    except Exception:
        logging.exception("Failed to send admin nudge")
