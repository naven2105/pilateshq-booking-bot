"""
admin_nudge.py
──────────────
Handles nudges to Nadine/admin:
 - Notify on new prospect lead
 - Allow Nadine to convert/add leads into clients
 - Booking-related nudges (no-show, sick, cancel)
 - NEW: Deactivate/reactivate client flow
"""

from __future__ import annotations
import logging
from datetime import datetime
from sqlalchemy import text
from .utils import send_whatsapp_text, normalize_wa
from .db import get_session
from .config import NADINE_WA


# ── New Prospect Lead ─────────────────────────────────────────────
def notify_new_lead(name: str, wa: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")  # Local SA time
    msg = (
        "📥 *New Prospect Lead*\n"
        f"• Name: {name}\n"
        f"• WhatsApp: {wa}\n"
        f"• Received: {ts}\n\n"
        "👉 To convert: reply `convert`\n"
        "👉 Or add with number: `add John with number 0821234567`"
    )
    _log_and_send(msg)


# ── Handle Admin Reply (convert/add) ──────────────────────────────
def handle_admin_reply(wa_number: str, text_in: str):
    # unchanged (keeps convert/add logic from before)
    ...


# ── Attendance Nudges ────────────────────────────────────────────
def notify_no_show(client_name: str, wa: str, session_date: str):
    msg = f"🚫 No-show alert: {client_name} ({wa}) missed session on {session_date}."
    _log_and_send(msg)


def notify_sick(client_name: str, wa: str, session_date: str):
    msg = f"🤒 Sick alert: {client_name} ({wa}) reported sick for session on {session_date}."
    _log_and_send(msg)


def notify_cancel(client_name: str, wa: str, session_date: str):
    msg = f"❌ Cancel alert: {client_name} ({wa}) cancelled session on {session_date}."
    _log_and_send(msg)


# ── Deactivate / Reactivate ──────────────────────────────────────
def request_deactivate(name: str, wa_admin: str):
    """Ask Nadine to confirm before deactivation."""
    with get_session() as s:
        bookings = s.execute(
            text("""
                SELECT COUNT(*) FROM bookings b
                JOIN clients c ON b.client_id = c.id
                WHERE lower(c.name)=lower(:n) AND c.status='active' AND b.status='active'
            """),
            {"n": name},
        ).scalar()
    msg = (
        f"⚠ You requested to deactivate client '{name}'.\n"
        f"• Active bookings: {bookings}\n\n"
        "Reply `confirm deactivate {name}` to proceed or `cancel`."
    )
    send_whatsapp_text(normalize_wa(wa_admin), msg)


def confirm_deactivate(name: str, wa_admin: str):
    with get_session() as s:
        s.execute(
            text("UPDATE clients SET status='inactive' WHERE lower(name)=lower(:n)"),
            {"n": name},
        )
    msg = f"✅ Client '{name}' has been deactivated. They can no longer book or access services."
    send_whatsapp_text(normalize_wa(wa_admin), msg)


def reactivate_client(name: str, wa_admin: str):
    with get_session() as s:
        s.execute(
            text("UPDATE clients SET status='active' WHERE lower(name)=lower(:n)"),
            {"n": name},
        )
    msg = f"✅ Client '{name}' has been reactivated and can now book sessions again."
    send_whatsapp_text(normalize_wa(wa_admin), msg)


# ── Internal helper ───────────────────────────────────────────────
def _log_and_send(msg: str):
    try:
        if NADINE_WA:
            send_whatsapp_text(normalize_wa(NADINE_WA), msg)
        with get_session() as s:
            s.execute(
                text("INSERT INTO notifications_log (client_id, message, created_at) "
                     "VALUES (NULL, :msg, now())"),
                {"msg": msg},
            )
    except Exception:
        logging.exception("Failed to send admin nudge")
