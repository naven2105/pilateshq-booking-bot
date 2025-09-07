# app/router.py
"""
Webhook + lightweight HTTP routes.
- GET /webhook : Meta verification (hub.mode=subscribe)
- POST /webhook: Handles inbound WhatsApp messages (Cloud API)
- GET  /      : Simple root status
NOTE: /health is defined in app/main.py to avoid duplicate endpoint errors.
"""

from __future__ import annotations

import logging
from flask import request
from typing import Any, Dict, Optional

from .config import ADMIN_NUMBERS, VERIFY_TOKEN
from .utils import (
    normalize_wa,
    send_whatsapp_text,
)

# Optional: simple public welcome used for non-admins
PUBLIC_WELCOME = (
    "Hi 👋 Thanks for messaging PilatesHQ!\n"
    "I can help with: \n"
    "• Address & parking\n"
    "• Group sizes\n"
    "• Equipment\n"
    "• Pricing\n"
    "• Schedule\n"
    "• How to start\n\n"
    "Reply with one of the topics (e.g., *Pricing*) or say *Book* to request a session.\n"
)

def _extract_message(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extract {from:'<wa_id>', text:'...'} from the Cloud API webhook JSON.
    Returns None if no text message present (e.g., status updates).
    """
    try:
        entry = payload.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])
        if not messages:
            return None
        msg = messages[0]
        if msg.get("type") != "text":
            # You can expand to support interactive/buttons, images, etc.
            return {
                "from": msg.get("from"),
                "text": "",
                "raw": msg,
            }
        return {
            "from": msg.get("from"),
            "text": msg.get("text", {}).get("body", "").strip(),
            "raw": msg,
        }
    except Exception:
        logging.exception("[webhook] failed to parse payload")
        return None


def register_routes(app):
    @app.get("/")
    def root():
        return "PilatesHQ bot is running.", 200

    # ─────────────────────────────────────────────────────────────
    # GET /webhook : Meta verification handshake
    # ─────────────────────────────────────────────────────────────
    @app.get("/webhook")
    def webhook_verify():
        try:
            mode = request.args.get("hub.mode")
            token = request.args.get("hub.verify_token")
            challenge = request.args.get("hub.challenge")

            if mode == "subscribe" and token == VERIFY_TOKEN:
                logging.info("[webhook] verification OK")
                return challenge, 200
            logging.warning("[webhook] verification failed (mode=%r, token=%r)", mode, token)
            return "forbidden", 403
        except Exception:
            logging.exception("[webhook] verification error")
            return "error", 500

    # ─────────────────────────────────────────────────────────────
    # POST /webhook : Cloud API messages
    # ─────────────────────────────────────────────────────────────
    @app.post("/webhook")
    def webhook():
        try:
            payload = request.get_json(silent=True) or {}
            msg = _extract_message(payload)
            if not msg:
                # Usually status/ack callbacks; must return 200 so Meta doesn’t retry
                return "ok", 200

            sender_wa = normalize_wa(msg["from"])
            text = (msg.get("text") or "").strip()

            # Detect admin (your ADMIN_NUMBERS are normalized on load)
            is_admin = sender_wa in ADMIN_NUMBERS

            if is_admin:
                # Keep your existing admin command handling if you have it.
                # For now, just confirm we saw it:
                if text:
                    send_whatsapp_text(sender_wa, f"Admin command received: {text}")
                else:
                    send_whatsapp_text(sender_wa, "Admin message received.")
                return "ok", 200

            # PUBLIC (non-admin) path: reply with a friendly menu/FAQ starter
            # You can route to a fuller NLU or FAQ flow here.
            if not text:
                send_whatsapp_text(sender_wa, PUBLIC_WELCOME)
                return "ok", 200

            # Very light keyword router for FAQs (you can replace with your RAG/FAQ handler)
            lower = text.lower()
            if "address" in lower or "parking" in lower:
                send_whatsapp_text(
                    sender_wa,
                    "📍 *Address & parking*\nWe’re at *71 Grant Ave, Norwood, Johannesburg*. "
                    "Safe off-street parking is available."
                )
            elif "group" in lower or "size" in lower:
                send_whatsapp_text(
                    sender_wa,
                    "👥 *Group sizes*\nGroups are capped at *6* to keep coaching personal."
                )
            elif "equipment" in lower:
                send_whatsapp_text(
                    sender_wa,
                    "🧰 *Equipment*\nReformers, Wall Units, Wunda chairs, small props, and mats."
                )
            elif "pricing" in lower or "price" in lower or "cost" in lower:
                send_whatsapp_text(
                    sender_wa,
                    "💳 *Pricing*\nGroups from *R180*. 1:1 and duo also available."
                )
            elif "schedule" in lower or "hours" in lower or "time" in lower:
                send_whatsapp_text(
                    sender_wa,
                    "🗓 *Schedule*\nWeekdays *06:00–18:00*; Sat *08:00–10:00*."
                )
            elif "start" in lower or "assessment" in lower or "book" in lower:
                send_whatsapp_text(
                    sender_wa,
                    "✅ *How to start*\nMost start with a *1:1 assessment*. "
                    "Reply *Book* to request your preferred day/time."
                )
            else:
                # Default: send the menu again
                send_whatsapp_text(sender_wa, PUBLIC_WELCOME)

            return "ok", 200

        except Exception:
            # Always return 200 to stop Meta retries; log the failure for us
            logging.exception("[webhook] error")
            return "ok", 200
