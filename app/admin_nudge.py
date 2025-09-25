"""
admin_nudge.py
──────────────
Handles nudges to Nadine/admin:
 - Notify on new prospect lead
 - Booking-related nudges (no-show, sick, cancel, deactivate, etc.)
"""

from __future__ import annotations
import logging
from datetime import datetime
from sqlalchemy import text
from .utils import send_whatsapp_template, normalize_wa
from .db import get_session
from .config import NADINE_WA

log = logging.getLogger(__name__)

TEMPLATE = "admin_alert"   # Approved WhatsApp template
LANG = "en"

# ── New Prospect Lead ─────────────────────────────────────────────
def notify_new_lead(name: str, wa: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")  # Local SA time if TZ set
    alert_text = f"📥 New Prospect: {name} ({wa}) at {ts}"
    _send_and_log(alert_text)


# ── Booking Nudges ────────────────────────────────────────────────
def notify_no_show(client_name: str, wa: str, session_date: str):
    alert_text = f"🚫 No-show: {client_name} ({wa}) missed session on {session_date}."
    _send_and_log(alert_text)

def notify_sick(client_name: str, wa: str, session_date: str):
    alert_text = f"🤒 Sick: {client_name} ({wa}) marked sick for session on {session_date}."
    _send_and_log(alert_text)

def notify_cancel(client_name: str, wa: str, session_date: str):
    alert_text = f"❌ Cancel: {client_name} ({wa}) cancelled session on {session_date}."
    _send_and_log(alert_text)

def request_deactivate(name: str, wa: str):
    alert_text = f"⚠ Request to deactivate client '{name}'. Reply 'confirm deactivate {name}' to proceed."
    _send_and_log(alert_text)

def confirm_deactivate(name: str, wa: str):
    alert_text = f"✅ Client '{name}' has been deactivated."
    _send_and_log(alert_text)


# ── Internal helper ───────────────────────────────────────────────
def _send_and_log(alert_text: str):
    try:
        if NADINE_WA:
            to_num = normalize_wa(NADINE_WA)
            log.info(f"[ADMIN_NUDGE] Sending WhatsApp template → {to_num}: {alert_text}")
            result = send_whatsapp_template(to_num, TEMPLATE, LANG, [alert_text])
            log.info(f"[ADMIN_NUDGE] WhatsApp send result: {result}")
        else:
            log.warning("[ADMIN_NUDGE] NADINE_WA not set in env, skipping WhatsApp send")

        with get_session() as s:
            s.execute(
                text("INSERT INTO notifications_log (client_id, message, created_at) "
                     "VALUES (NULL, :msg, now())"),
                {"msg": alert_text},
            )
            log.info("[ADMIN_NUDGE] Inserted nudge into notifications_log")
    except Exception:
        log.exception("[ADMIN_NUDGE] Failed to send admin nudge")
