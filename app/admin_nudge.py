# app/admin_nudge.py
"""
admin_nudge.py
──────────────
Handles nudges to Nadine/admin:
 - Notify on new prospect lead
 - Allow Nadine to convert/add leads into clients
 - Placeholders for booking-related nudges (no-show, sick, cancel, etc.)
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
    """Notify Nadine of a new prospect lead and log it."""
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    msg = (
        "📥 *New Prospect Lead*\n"
        f"• Name: {name}\n"
        f"• WhatsApp: {wa}\n"
        f"• Received: {ts}\n\n"
        "👉 To convert: reply `convert {wa}`\n"
        "👉 Or add with number: `add John with number 0821234567`"
    )
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
        logging.exception("Failed to notify admin about new lead")


# ── Handle Admin Reply ────────────────────────────────────────────
def handle_admin_reply(wa_number: str, text_in: str):
    """
    Handle Nadine’s replies like:
    - convert 2773...
    - add John with number 082...
    """
    wa = normalize_wa(wa_number)
    lower = (text_in or "").strip().lower()

    if lower.startswith("convert "):
        lead_wa = normalize_wa(text_in.split(" ", 1)[1])
        with get_session() as s:
            lead = s.execute(
                text("SELECT id, name FROM leads WHERE wa_number=:wa"),
                {"wa": lead_wa},
            ).mappings().first()
            if not lead:
                send_whatsapp_text(wa, f"⚠ No lead found with number {lead_wa}.")
                return
            s.execute(
                text("INSERT INTO clients (name, wa_number, phone, package_type) "
                     "VALUES (:n, :wa, :wa, 'manual') ON CONFLICT DO NOTHING"),
                {"n": lead["name"], "wa": lead_wa},
            )
            s.execute(
                text("UPDATE leads SET status='converted' WHERE wa_number=:wa"),
                {"wa": lead_wa},
            )
        send_whatsapp_text(wa, f"✅ Lead {lead['name']} ({lead_wa}) converted to client.")
        return

    if lower.startswith("add "):
        # crude parse: "add John with number 0821234567"
        parts = text_in.split("with number")
        if len(parts) == 2:
            name = parts[0].replace("add", "").strip()
            number = normalize_wa(parts[1].strip())
            with get_session() as s:
                s.execute(
                    text("INSERT INTO clients (name, wa_number, phone, package_type) "
                         "VALUES (:n, :wa, :wa, 'manual') ON CONFLICT DO NOTHING"),
                    {"n": name, "wa": number},
                )
            send_whatsapp_text(wa, f"✅ Client '{name}' added with number {number}.")
            return

    # fallback
    send_whatsapp_text(
        wa,
        "⚠ Unknown admin reply. Use `convert <wa>` or `add <name> with number <cell>`."
    )


# ── Placeholders for Future Nudges ────────────────────────────────
def notify_no_show(client_name: str, wa: str, session_date: str):
    """Placeholder: Notify Nadine/admin when a client is marked as no-show."""
    msg = f"🚫 No-show alert: {client_name} ({wa}) missed session on {session_date}."
    _log_and_send(msg)


def notify_sick(client_name: str, wa: str, session_date: str):
    """Placeholder: Notify Nadine/admin when a client is marked as sick."""
    msg = f"🤒 Sick alert: {client_name} ({wa}) reported sick for session on {session_date}."
    _log_and_send(msg)


def notify_cancel(client_name: str, wa: str, session_date: str):
    """Placeholder: Notify Nadine/admin when a client cancels a session."""
    msg = f"❌ Cancel alert: {client_name} ({wa}) cancelled session on {session_date}."
    _log_and_send(msg)


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
