#app/admin_notify
"""
admin_notify.py
────────────────
Handles logging + sending messages to clients/admins.
Replaces SQL logging with Google Sheets + webhook audit.
"""

import logging
from datetime import datetime
from .utils import send_whatsapp_text, normalize_wa, safe_execute, post_to_webhook
from .config import WEBHOOK_BASE, TIMEZONE

log = logging.getLogger(__name__)


# ───────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────
def _log_notification(recipient: str, message: str, context: str = "general"):
    """
    Log a notification to the Google Sheets "Logs" tab via webhook.
    """
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        payload = {
            "action": "log_action",
            "wa_number": recipient,
            "action_type": context,
            "message": message,
            "timestamp": ts,
        }
        res = post_to_webhook(f"{WEBHOOK_BASE}/sheets", payload)
        log.info(f"[NOTIFY_LOG] {recipient} ({context}) → {res}")
    except Exception as e:
        log.error(f"❌ Failed to log notification ({context}): {e}")


# ───────────────────────────────────────────────
# Core Notification Functions
# ───────────────────────────────────────────────
def notify_client(wa_number: str, message: str):
    """Send WhatsApp text to a client and record in Logs sheet."""
    if not wa_number:
        log.warning("[notify_client] Missing WA number, skipping send.")
        return

    wa_norm = normalize_wa(wa_number)
    safe_execute(send_whatsapp_text, wa_norm, message, label="notify_client")
    _log_notification(wa_norm, message, context="client")


def notify_admin(message: str, to_wa: str):
    """Send WhatsApp text to admin and record in Logs sheet."""
    if not to_wa:
        log.warning("[notify_admin] Missing admin WA number, skipping send.")
        return

    wa_norm = normalize_wa(to_wa)
    safe_execute(send_whatsapp_text, wa_norm, message, label="notify_admin")
    _log_notification(wa_norm, message, context="admin")
