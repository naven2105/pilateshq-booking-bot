# app/router.py
from __future__ import annotations

import logging
import re
from typing import Optional

from flask import request, jsonify

from .utils import normalize_wa, reply_to_whatsapp
from .admin import handle_admin_action
from .public import handle_public_greeting, handle_public_message
from .config import VERIFY_TOKEN, ADMIN_NUMBERS  # ADMIN_NUMBERS can be empty list if you want no admins yet


def _extract_incoming(body: dict) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Parse WhatsApp Cloud API webhook payload.
    Returns (from_wa, text, reply_id).
    """
    try:
        entry = body.get("entry", [])[0]
        change = entry.get("changes", [])[0]
        value = change.get("value", {})
        messages = value.get("messages", [])
        if not messages:
            return None, None, None
        msg = messages[0]
        from_wa = msg.get("from")
        text = None
        if msg.get("type") == "text":
            text = msg.get("text", {}).get("body")
        elif msg.get("type") == "interactive":
            # list/button replies:
            text = msg.get("interactive", {}).get("list_reply", {}).get("title") or \
                   msg.get("interactive", {}).get("button_reply", {}).get("title")
        reply_id = msg.get("id")
        return from_wa, text, reply_id
    except Exception:
        logging.exception("Failed to parse webhook payload")
        return None, None, None


def register_routes(app):

    # Health
    @app.get("/health")
    def health():
        return "ok", 200

    # Webhook verify (Meta setup)
    @app.get("/webhook")
    def webhook_verify():
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token == VERIFY_TOKEN:
            return challenge, 200
        return "forbidden", 403

    # Webhook receiver
    @app.post("/webhook")
    def webhook():
        try:
            data = request.get_json(silent=True) or {}
            sender, text_in, reply_id = _extract_incoming(data)
            if not sender:
                return "ok", 200

            sender_e164 = normalize_wa(sender)
            is_admin = sender_e164 in {normalize_wa(n) for n in ADMIN_NUMBERS if n}

            if is_admin:
                # Your existing admin command router
                handle_admin_action(sender, reply_id)
                return "ok", 200

            # Non-admin: greet on first contact / greeting, else general helper
            msg = (text_in or "").strip()
            if re.match(r"^\s*(hi|hello|hey|morning|afternoon|evening)\s*$", msg, flags=re.I):
                handle_public_greeting(sender, reply_id)
            else:
                handle_public_message(sender, msg, reply_id)

            return "ok", 200

        except Exception:
            logging.exception("webhook failed")
            return "ok", 200
