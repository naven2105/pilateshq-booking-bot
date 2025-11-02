"""
client_attendance.py
────────────────────
Handles attendance updates from clients:
 - Sick today
 - Cannot attend / cancel today
 - Running late

Now integrated with Google Sheets via Apps Script Webhook.
"""

import logging
import os
import requests
from datetime import datetime
from .utils import send_whatsapp_text, send_safe_message, safe_execute

log = logging.getLogger(__name__)

# Your deployed Google Apps Script Web App URL
APPS_SCRIPT_URL = os.getenv("APPS_SCRIPT_URL")
NADINE_WA = os.getenv("NADINE_WA", "")


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
def _post_to_apps_script(action: str, wa_number: str, status: str):
    """
    Notify Apps Script to update today's booking for a given client.
    The Apps Script locates the row in 'Sessions' by wa_number and date.
    """
    if not APPS_SCRIPT_URL:
        log.warning("⚠️ APPS_SCRIPT_URL not set; skipping Sheets update.")
        return

    try:
        payload = {
            "action": action,
            "wa_number": wa_number,
            "status": status,
            "timestamp": datetime.now().isoformat(),
        }
        res = requests.post(APPS_SCRIPT_URL, json=payload, timeout=10)
        log.info(f"📤 Sent attendance update to Apps Script: {payload} → {res.status_code}")
    except Exception as e:
        log.error(f"❌ Failed to post attendance update: {e}")


# ─────────────────────────────────────────────────────────────
# Sick Today
# ─────────────────────────────────────────────────────────────
def mark_sick_today(wa_number: str):
    """Mark today's session as 'sick' and notify admin."""
    log.info(f"[client_attendance] mark_sick_today → {wa_number}")

    _post_to_apps_script("update_status_today", wa_number, "sick")

    safe_execute(
        "client_sick_ok",
        send_whatsapp_text,
        wa_number,
        "🤒 Got it — your session today is marked as *sick*. Rest well 💜",
    )

    # Notify Nadine
    send_safe_message(
        NADINE_WA,
        f"📋 Client ({wa_number}) marked today as *sick*.",
        label="admin_sick_notice",
    )


# ─────────────────────────────────────────────────────────────
# Cancel Today
# ─────────────────────────────────────────────────────────────
def cancel_today(wa_number: str):
    """Cancel today's session (status='cancelled')."""
    log.info(f"[client_attendance] cancel_today → {wa_number}")

    _post_to_apps_script("update_status_today", wa_number, "cancelled")

    safe_execute(
        "client_cancel_today_ok",
        send_whatsapp_text,
        wa_number,
        "❌ Your session today has been *cancelled*. Thanks for letting us know.",
    )

    send_safe_message(
        NADINE_WA,
        f"📋 Client ({wa_number}) *cancelled* today’s session.",
        label="admin_cancel_notice",
    )


# ─────────────────────────────────────────────────────────────
# Running Late
# ─────────────────────────────────────────────────────────────
def running_late(wa_number: str):
    """Notify Nadine that a client is running late."""
    log.info(f"[client_attendance] running_late → {wa_number}")

    safe_execute(
        "client_late_ok",
        send_whatsapp_text,
        wa_number,
        "⌛ Thanks for letting us know. Drive safe — Nadine has been notified.",
    )

    send_safe_message(
        NADINE_WA,
        f"🚗 Client ({wa_number}) reported they’re *running late*.",
        label="admin_late_notice",
    )
