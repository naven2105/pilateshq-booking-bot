# app/router.py
import logging
from flask import request

from .config import VERIFY_TOKEN
from .utils import normalize_wa
from .admin import _is_admin, handle_admin_action
from .onboarding import handle_onboarding

def register_routes(app):
    """Register webhook routes on the Flask app."""

    @app.route("/", methods=["GET"])
    def health():
        return "OK", 200

    @app.route("/webhook", methods=["GET"])
    def verify_webhook():
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if token == VERIFY_TOKEN:
            logging.info("✅ Webhook verified")
            return challenge, 200
        logging.warning("❌ Webhook verification failed")
        return "Verification failed", 403

    @app.route("/webhook", methods=["POST"])
    def webhook():
        data = request.get_json(silent=True) or {}
        logging.debug(f"[WEBHOOK DATA] {data}")

        try:
            for entry in data.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    # Message statuses (sent/delivered/read) — acknowledge quickly
                    if "statuses" in value:
                        logging.debug(f"[STATUS] {value.get('statuses')}")
                        continue

                    messages = value.get("messages", [])
                    for message in messages:
                        sender = normalize_wa(message.get("from", ""))
                        # ---------- INTERACTIVE FIRST ----------
                        if "interactive" in message:
                            reply_id = (
                                message["interactive"].get("button_reply", {}).get("id")
                                or message["interactive"].get("list_reply", {}).get("id")
                            )
                            logging.info(f"[ROUTER] interactive from={sender} id={reply_id} admin={_is_admin(sender)}")
                            if _is_admin(sender):
                                return _safe_ok(handle_admin_action(sender, reply_id))
                            # Non-admin interactive goes to onboarding (or your default handler)
                            return _safe_ok(handle_onboarding(sender, reply_id))

                        # ---------- TEXT ----------
                        if "text" in message:
                            msg_text = message["text"].get("body", "").strip()
                            is_admin = _is_admin(sender)
                            logging.info(f"[ROUTER] text from={sender} admin={is_admin} msg='{msg_text}'")

                            if is_admin:
                                # Always route admin text to admin handler (NLP-first)
                                return _safe_ok(handle_admin_action(sender, msg_text))

                            # Non-admins: greet → onboarding, otherwise your default user flow
                            low = msg_text.lower()
                            if low in ("hi", "hello", "start"):
                                return _safe_ok(handle_onboarding(sender))
                            # Default for regular users
                            return _safe_ok(handle_onboarding(sender, msg_text))

        except Exception as e:
            logging.exception(f"[ERROR webhook]: {e}")

        return "ok", 200


def _safe_ok(result):
    """
    WhatsApp handlers usually send messages and return None;
    Flask requires a valid response—normalize to ('ok', 200).
    """
    return ("ok", 200)
