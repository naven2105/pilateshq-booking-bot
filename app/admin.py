# app/admin.py
from __future__ import annotations
import logging
from typing import Optional
from .utils import send_whatsapp_text, normalize_wa

def handle_admin_action(from_wa: str, msg_id: Optional[str], body: str, btn_id: Optional[str] = None):
    """
    Handle inbound admin actions from WhatsApp.
    For now: simple menu stub. Can be expanded later.
    """
    logging.info(f"[ADMIN] from={from_wa} body={body!r} btn_id={btn_id!r}")

    # Example menu options
    if body.lower() in {"hi", "menu", "help"}:
        send_whatsapp_text(
            normalize_wa(from_wa),
            "🛠 Admin\nChoose an option below..\n\n1) View Inbox\n2) Manage Sessions\n3) Reports"
        )
        return

    # Placeholder for buttons or more advanced actions
    send_whatsapp_text(normalize_wa(from_wa), "⚠ Unknown admin command. Please reply 'menu' for options.")
