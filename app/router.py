# app/router.py
from __future__ import annotations

import logging
from flask import request

from app.config import VERIFY_TOKEN, NADINE_WA
from app.utils import normalize_wa, send_whatsapp_text, notify_admin
from app.onboarding import handle_onboarding, capture_onboarding_free_text
from app.admin import handle_admin_action

from . import crud

def handle_incoming_text(sender_wa: str, body_text: str):
    wa = normalize_wa(sender_wa)
    txt = (body_text or "").strip().lower()

    # ... your existing routing ...

    # Only for regular clients (not admin UI):
    if "cancel" in txt:
        # Try to infer the client’s next upcoming booking
        info = crud.find_next_upcoming_booking_by_wa(wa)
        if info:
            # Tell the client we’ve recorded their request (no DB change)
            send_whatsapp_text(wa,
                "Thanks — we’ve notified the studio. An admin will confirm your cancellation shortly. 🙏")

            # Notify admin with the details (no DB write here)
            human_name = info.get("name") or wa
            hhmm = str(info["start_time"])[:5]
            msg = (
                "❗ Cancel request received\n"
                f"• Client: {human_name} ({info['wa_number']})\n"
                f"• Session: {info['session_date']} {hhmm}\n"
                "No database change was made. Please review and cancel if needed."
            )
            notify_admin(msg)
        else:
            # No upcoming booking found
            send_whatsapp_text(wa,
                "We couldn’t find an upcoming booking to cancel. If you think this is a mistake, please reply with the date/time.")
        return

def _admin_set():
    """Single-admin mode: only Nadine's number is admin."""
    nums = set()
    if NADINE_WA:
        nums.add(normalize_wa(NADINE_WA))
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
        Always returns 200 OK to Meta.
        """
        data = request.get_json(silent=True) or {}
        logging.debug(f"[WEBHOOK DATA] {data}")

        try:
            if data.get("object") != "whatsapp_business_account":
                return "ignored", 200

            for entry in data.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})

                    # 1) Ignore delivery/status callbacks
                    if value.get("statuses"):
                        logging.debug("[STATUS EVENT] ignored")
                        continue

                    # 2) Process inbound messages
                    for message in value.get("messages", []):
                        sender_raw = message.get("from", "")
                        sender = normalize_wa(sender_raw)
                        is_admin = sender in ADMIN_WA_SET

                        # Interactive replies
                        if "interactive" in message:
                            inter = message["interactive"]
                            reply_id = (
                                inter.get("button_reply", {}).get("id")
                                or inter.get("list_reply", {}).get("id")
                            )
                            if not reply_id:
                                logging.debug("[INTERACTIVE] no reply id")
                                continue

                            logging.info(f"[INTERACTIVE] {sender} -> {reply_id}")

                            if is_admin:
                                handle_admin_action(sender, reply_id)
                            else:
                                handle_onboarding(sender, reply_id)
                            continue

                        # Plain text
                        msg_text = (message.get("text", {}) or {}).get("body", "").strip()
                        if not msg_text:
                            logging.debug("[TEXT] empty body")
                            continue

                        logging.info(f"[TEXT] {sender} -> {msg_text}")

                        if is_admin:
                            # Admin uses NLP for all actions
                            handle_admin_action(sender, msg_text)
                            continue

                        # Client path
                        low = msg_text.lower()
                        if low in ("hi", "hello", "start"):
                            handle_onboarding(sender, None)
                        else:
                            # Either captures awaited onboarding free text, or shows menu
                            capture_onboarding_free_text(sender, msg_text)

        except Exception as e:
            logging.exception(f"[ERROR webhook]: {e}")

        # Always ACK to Meta
        return "ok", 200
