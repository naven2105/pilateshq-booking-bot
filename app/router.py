# app/router.py
from __future__ import annotations

import logging
from datetime import datetime
from flask import request

from app.config import VERIFY_TOKEN, NADINE_WA, ADMIN_WA_LIST
from app.utils import normalize_wa, send_whatsapp_text
from app.onboarding import handle_onboarding, capture_onboarding_free_text
from app.admin import handle_admin_action

# Build admin set (normalize to +27… form)
def _admin_set():
    nums = set()
    if NADINE_WA:
        nums.add(normalize_wa(NADINE_WA))
    if ADMIN_WA_LIST:
        for n in str(ADMIN_WA_LIST).split(","):
            if n.strip():
                nums.add(normalize_wa(n.strip()))
    return nums

ADMIN_WA_SET = _admin_set()


def register_routes(app):
    """
    Registers webhook routes on the provided Flask app.
    NOTE: This module does not define "/" health routes to avoid endpoint clashes.
    """

    @app.get("/webhook")
    def verify_webhook():
        """Meta verification challenge."""
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if token == VERIFY_TOKEN and challenge:
            logging.info("✅ Webhook verified")
            return challenge, 200
        logging.warning("❌ Webhook verification failed")
        return "Verification failed", 403

    @app.post("/webhook")
    def webhook():
        """
        WhatsApp inbound handler.
        Supports:
          - text messages (admin NLP & client onboarding)
          - interactive button/list replies
          - ignores status notifications
        Always returns a simple 200 OK to Meta.
        """
        data = request.get_json(silent=True) or {}
        logging.debug(f"[WEBHOOK DATA] {data}")

        try:
            if data.get("object") != "whatsapp_business_account":
                return "ignored", 200

            for entry in data.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})

                    # 1) Ignore status callbacks
                    if value.get("statuses"):
                        logging.debug("[STATUS EVENT] ignored")
                        continue

                    # 2) Process inbound messages
                    for message in value.get("messages", []):
                        sender_raw = message.get("from", "")
                        sender = normalize_wa(sender_raw)

                        # Admin or not?
                        is_admin = sender in ADMIN_WA_SET

                        # Interactive replies (buttons / lists)
                        if "interactive" in message:
                            inter = message["interactive"]
                            reply_id = (
                                inter.get("button_reply", {}).get("id")
                                or inter.get("list_reply", {}).get("id")
                            )
                            if not reply_id:
                                logging.debug("[INTERACTIVE] no reply id found")
                                continue

                            logging.info(f"[INTERACTIVE] {sender} -> {reply_id}")

                            if is_admin:
                                # Route interactive payload to admin handler
                                handle_admin_action(sender, reply_id)
                            else:
                                # Route interactive payload to onboarding/menu
                                handle_onboarding(sender, reply_id)
                            continue  # proceed to next message

                        # Text messages
                        msg_text = (message.get("text", {}) or {}).get("body", "").strip()
                        if not msg_text:
                            logging.debug("[TEXT] empty body")
                            continue

                        logging.info(f"[TEXT] {sender} -> {msg_text}")

                        if is_admin:
                            # Entirely NLP-based for admin
                            handle_admin_action(sender, msg_text)
                            continue

                        # Client path: try capture in-progress onboarding first
                        # If not in an awaiting state, treat "hi/hello/start" as entry to menu
                        low = msg_text.lower()
                        if low in ("hi", "hello", "start"):
                            handle_onboarding(sender, None)
                        else:
                            # free text could be onboarding capture (name/medical/etc.)
                            # If not awaiting, onboarding will show menu
                            capture_onboarding_free_text(sender, msg_text)

        except Exception as e:
            logging.exception(f"[ERROR webhook]: {e}")

        # Always ACK 200 to Meta within 10s
        return "ok", 200
