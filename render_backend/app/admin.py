# app/admin.py
"""
admin.py
────────
Thin entrypoint.
Delegates all admin commands to admin_core.
"""

import logging
from .admin_core import handle_admin_action

log = logging.getLogger(__name__)

def handle_admin_command(message_text: str, wa_number: str) -> dict:
    """
    Entry point for WhatsApp admin messages.
    Routes admin commands to the core handler.

    Args:
        message_text: The text body received from WhatsApp (e.g., 'pause', 'report').
        wa_number: The sender’s WhatsApp number in E.164 format (e.g., '27721234567').

    Returns:
        dict: Result dictionary from admin_core.handle_admin_action()
    """
    log.info(f"[admin] Command from {wa_number}: {message_text}")
    return handle_admin_action(message_text, wa_number)
