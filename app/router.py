# app/router.py
from flask import request
import logging

from app.config import VERIFY_TOKEN
from app.onboarding import handle_onboarding
from app.admin import handle_admin_message

def register_routes(app):
    """Register all routes with the Flask app."""

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
        data = request.get_json()
        logging.debug(f"[WEBHOOK DATA] {data}")

        try:
            for entry in data.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    messages = value.get("messages", [])
                    for message in messages:
                        sender = message["from"]

                        # First-time or returning client
                        if "text" in message:
                            msg_text = message["text"]["body"].strip().lower()
                            if msg_text in ["hi", "hello", "start"]:
                                return handle_onboarding(sender)
                            else:
                                return handle_admin_message(sender, msg_text)

                        # Interactive replies (buttons / lists)
                        if "interactive" in message:
                            reply_id = (
                                message["interactive"].get("button_reply", {}).get("id")
                                or message["interactive"].get("list_reply", {}).get("id")
                            )
                            if reply_id:
                                logging.info(f"[USER CHOICE] {reply_id}")
                                if reply_id.startswith("ADMIN"):
                                    return handle_admin_message(sender, reply_id)
                                else:
                                    return handle_onboarding(sender, reply_id)

        except Exception as e:
            logging.exception(f"[ERROR webhook]: {str(e)}")

        return "ok", 200
