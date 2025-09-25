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

log = logging.getLogger(__name__)


# ── New Prospect Lead ─────────────────────────────────────────────
def notify_new_lead(name: str, wa: str):
    """Notify Nadine of a new prospect lead and log it."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")  # local SA time if TZ is set
    msg = (
        "📥 *New Prospect Lead*\n"
        f"• Name: {name}\n"
        f"• WhatsApp: {wa}\n"
        f"• Received: {ts}\n\n"
        "👉 To convert: reply `convert`\n"
        "👉 Or add with number: `add John with number 0821234567`"
    )

    log.info(f"[ADMIN_NUDGE] Trigger notify_new_lead for name={name}, wa={wa}")

    try:
        if NADINE_WA:
            to_num = normalize_wa(NADINE_WA)
            log.info(f"[ADMIN_NUDGE] Sending WhatsApp lead alert → {to_num}")
            result = send_whatsapp_text(to_num, msg)
            log.info(f"[ADMIN_NUDGE] WhatsApp send result: {result}")
        else:
            log.warning("[ADMIN_NUDGE] NADINE_WA not set in env, skipping WhatsApp send")

        with get_session() as s:
            s.execute(
                text("INSERT INTO notifications_log (client_id, message, created_at) "
                     "VALUES (NULL, :msg, now())"),
                {"msg": msg},
            )
            log.info("[ADMIN_NUDGE] Inserted new lead message into notifications_log")

    except Exception:
        log.exception("[ADMIN_NUDGE] Failed to notify admin about new lead")


# ── Handle Admin Reply ────────────────────────────────────────────
def handle_admin_reply(wa_number: str, text_in: str):
    """Handle Nadine’s replies: convert, add, etc."""
    wa = normalize_wa(wa_number)
    lower = (text_in or "").strip().lower()
    log.info(f"[ADMIN_NUDGE] handle_admin_reply from={wa} text={lower!r}")

    if lower.startswith("convert"):
        parts = text_in.split()
        if len(parts) == 1:
            # Shortcut: convert most recent unconverted lead
            with get_session() as s:
                lead = s.execute(
                    text("""
                        SELECT id, name, wa_number
                        FROM leads
                        WHERE status IS NULL OR status != 'converted'
                        ORDER BY created_at DESC
                        LIMIT 1
                    """)
                ).mappings().first()
                if not lead:
                    send_whatsapp_text(wa, "⚠ No unconverted leads available.")
                    return
                s.execute(
                    text("INSERT INTO clients (name, wa_number, phone, package_type) "
                         "VALUES (:n, :wa, :wa, 'manual') ON CONFLICT DO NOTHING"),
                    {"n": lead["name"], "wa": lead["wa_number"]},
                )
                s.execute(
                    text("UPDATE leads SET status='converted' WHERE wa_number=:wa"),
                    {"wa": lead["wa_number"]},
                )
            send_whatsapp_text(wa, f"✅ Most recent lead {lead['name']} ({lead['wa_number']}) converted to client.")
            return

        else:
            # Old style: "convert <wa>"
            lead_wa = normalize_wa(parts[1])
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
        "⚠ Unknown admin reply. Use `convert` (latest lead), "
        "`convert <wa>`, or `add <name> with number <cell>`."
    )


# ── Placeholders for Future Nudges ─────────────────────────────────────────────
def notify_no_show(client_name: str, wa: str, session_date: str):
    msg = f"🚫 No-show alert: {client_name} ({wa}) missed session on {session_date}."
    _log_and_send(msg)


def notify_sick(client_name: str, wa: str, session_date: str):
    msg = f"🤒 Sick alert: {client_name} ({wa}) reported sick for session on {session_date}."
    _log_and_send(msg)


def notify_cancel(client_name: str, wa: str, session_date: str):
    msg = f"❌ Cancel alert: {client_name} ({wa}) cancelled session on {session_date}."
    _log_and_send(msg)


# ── Internal helper ───────────────────────────────────────────────
def _log_and_send(msg: str):
    try:
        if NADINE_WA:
            send_whatsapp_text(normalize_wa(NADINE_WA), msg)
            log.info(f"[ADMIN_NUDGE] Nudge sent → {NADINE_WA}")
        else:
            log.warning("[ADMIN_NUDGE] NADINE_WA not set, skipping nudge send")

        with get_session() as s:
            s.execute(
                text("INSERT INTO notifications_log (client_id, message, created_at) "
                     "VALUES (NULL, :msg, now())"),
                {"msg": msg},
            )
            log.info("[ADMIN_NUDGE] Inserted nudge into notifications_log")
    except Exception:
        log.exception("[ADMIN_NUDGE] Failed to send admin nudge")
