# app/router_client.py
"""
router_client.py
────────────────
Handles client messages (non-admin).
Delegates to client_commands (bookings, cancel, message Nadine).
Now defaults to the interactive FAQ menu for unrecognised messages,
with automatic fallback to static FAQs if needed.
"""

import logging
from flask import jsonify
from . import client_commands
from .utils import send_whatsapp_text, safe_execute
from .db import get_session
from sqlalchemy import text
from .client_faqs import handle_faq_message, handle_faq_button  # ✅ Integrated FAQ system
from .faqs import build_faq_text  # ✅ Fallback for static FAQs

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
    msg_type = msg.get("type")

    # ── Handle interactive FAQ buttons ───────────────────────────────
    if msg_type == "button":
        button_id = msg["button"]["payload"]
        if handle_faq_button(wa, button_id):
            return jsonify({"status": "ok", "role": "client_faq_button"}), 200

    # ── Handle FAQ trigger words ─────────────────────────────────────
    if any(k in txt for k in ["faq", "faqs", "help", "questions"]):
        # Try sending interactive FAQ
        try:
            handle_faq_message(wa, txt)
        except Exception as e:
            log.warning(f"[FAQ] Interactive FAQ failed ({e}); using fallback text.")
            safe_execute(send_whatsapp_text, wa, build_faq_text())
        return jsonify({"status": "ok", "role": "client_faq"}), 200

    # ── Recognised booking and admin-type commands ───────────────────
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

    # ── Default: unknown message → trigger FAQ menu or fallback ──────
    try:
        handle_faq_message(wa, "faq")
    except Exception as e:
        log.warning(f"[FAQ] Fallback trigger failed ({e}); sending plain FAQ text.")
        safe_execute(send_whatsapp_text, wa, build_faq_text())

    return jsonify({"status": "ok", "role": "client_faq_default"}), 200
