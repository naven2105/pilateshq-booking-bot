"""
admin_nudge.py
──────────────
Simplified version for Google Sheets setup.
Handles admin notifications (nudges) to Nadine for:
 - New prospects
 - Booking updates
 - Attendance issues (sick, no-show, cancel)
"""

import logging
import os
from datetime import datetime
from .utils import safe_execute, send_whatsapp_template

log = logging.getLogger(__name__)

# ── Environment ──
NADINE_WA = os.getenv("NADINE_WA", "")
TEMPLATE_LANG = os.getenv("TEMPLATE_LANG", "en_US")

# Use generic templates
ADMIN_TEMPLATE = "admin_generic_alert_us"
CLIENT_TEMPLATE = "client_generic_alert_us"


def notify_new_lead(wa_number: str, message: str):
    """
    Notify Nadine about a new WhatsApp lead or greeting.
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    body = f"📥 New Prospect: {wa_number} at {ts}. Msg: {message}"
    log.info(f"[ADMIN NUDGE] notify_new_lead → {body}")

    safe_execute(
        send_whatsapp_template,
        NADINE_WA,
        ADMIN_TEMPLATE,
        TEMPLATE_LANG,
        [body],
        label="notify_new_lead"
    )


def notify_booking_update(summary: str):
    """
    Generic admin booking update (used for confirmations or changes).
    """
    log.info(f"[ADMIN NUDGE] booking update → {summary}")
    safe_execute(
        send_whatsapp_template,
        NADINE_WA,
        ADMIN_TEMPLATE,
        TEMPLATE_LANG,
        [summary],
        label="notify_booking_update"
    )


def notify_client(name: str, message: str):
    """
    Send a generic message to a client using the client_generic_alert_us template.
    """
    log.info(f"[CLIENT MSG] {name} → {message}")
    safe_execute(
        send_whatsapp_template,
        name,
        CLIENT_TEMPLATE,
        TEMPLATE_LANG,
        [message],
        label="notify_client"
    )
