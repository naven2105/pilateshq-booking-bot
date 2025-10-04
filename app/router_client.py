"""
router_client.py
────────────────
Handles client messages (non-admin).
Delegates to client_commands (bookings, cancel, message Nadine).
"""

import logging
from flask import jsonify
from . import client_commands
from .prospect import CLIENT_MENU
from .utils import send_whatsapp_text, safe_execute
from .db import get_session
from sqlalchemy import text

log = logging.getLogger(__name__)


def client_get(wa: str):
    """Fetch client record by WhatsApp number."""
    with get_session() as s:
        row = s.execute(
            text("SELECT id, name FROM clients WHERE wa_number=:wa"),
            {"wa": wa},
        ).first()
        if row:
            return {"id": row[0], "name": row[1]}
        return None


def handle_client(msg, wa: str, text_in: str, client: dict):
    """Handle messages from registered clients."""
    txt = text_in.strip().lower()

    if txt in ["bookings", "my bookings", "sessions"]:
        client_commands.show_bookings(wa)
        return jsonify({"status": "ok", "role": "client_bookings"}), 200

    if txt in ["cancel next", "cancel upcoming"]:
        client_commands.cancel_next(wa)
        return jsonify({"status": "ok", "role": "client_cancel_next"}), 200

    if txt.startswith("cancel "):
        parts = txt.split()
        if len(parts) >= 3:
            _, day, time = parts[0:3]
            client_commands.cancel_specific(wa, day, time)
            return jsonify({"status": "ok", "role": "client_cancel_specific"}), 200

    if txt.startswith("message nadine"):
        msg_out = text_in[len("message nadine"):].strip()
        client_commands.message_nadine(wa, client["name"], msg_out)
        return jsonify({"status": "ok", "role": "client_message"}), 200

    # Default → client menu
    safe_execute(send_whatsapp_text, wa, CLIENT_MENU.format(name=client["name"]))
    return jsonify({"status": "ok", "role": "client_menu"}), 200
