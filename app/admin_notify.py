"""
admin_notify.py
───────────────
Handles logging + sending messages to clients/admins.
"""

import logging
from sqlalchemy import text
from .db import get_session
from .utils import send_whatsapp_text, normalize_wa, safe_execute

log = logging.getLogger(__name__)


def _log_notification(client_id: int | None, message: str):
    with get_session() as s:
        s.execute(
            text("INSERT INTO notifications_log (client_id, message, created_at) "
                 "VALUES (:cid, :msg, now())"),
            {"cid": client_id, "msg": message},
        )


def notify_client(wa_number: str, message: str):
    """Send WhatsApp text to a client and log it."""
    if not wa_number:
        return
    safe_execute(send_whatsapp_text, normalize_wa(wa_number), message, label="notify_client")
    with get_session() as s:
        row = s.execute(
            text("SELECT id FROM clients WHERE wa_number=:wa"),
            {"wa": normalize_wa(wa_number)},
        ).first()
        if row:
            _log_notification(row[0], message)


def notify_admin(message: str, to_wa: str):
    """Send WhatsApp text to admin and log it."""
    safe_execute(send_whatsapp_text, normalize_wa(to_wa), message, label="notify_admin")
    _log_notification(None, message)
