from flask import request
import logging
from .config import VERIFY_TOKEN
from .utils import normalize_wa
from .onboarding import handle_onboarding, capture_onboarding_free_text
from .admin import handle_admin_action
from .wellness import handle_wellness_message

def register_routes(app):
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
        data = request.get_json() or {}
        logging.debug(f"[WEBHOOK DATA] {data}")

        try:
            for entry in data.get("entry", []):
                for change in entry.get("changes", []):
                    for message in change.get("value", {}).get("messages", []):
                        sender = normalize_wa(message["from"])

                        # interactive replies first
                        if "interactive" in message:
                            rep = message["interactive"]
                            reply_id = (
                                rep.get("button_reply", {}).get("id") or
                                rep.get("list_reply", {}).get("id")
                            )
                            if reply_id:
                                logging.info(f"[USER CHOICE] {reply_id}")
                                if reply_id.startswith("ADMIN"):
                                    return handle_admin_action(sender, reply_id)
                                return handle_onboarding(sender, reply_id)

                        # plain text
                        if "text" in message:
                            msg_text = (message["text"]["body"] or "").strip()
                            upper = msg_text.upper()
                            if upper in ("HI","HELLO","START","MENU","MAIN_MENU"):
                                return handle_onboarding(sender, "ROOT_MENU")

                            # if onboarding is awaiting a free-text answer
                            return capture_onboarding_free_text(sender, msg_text)

                        # fallback
                        return handle_onboarding(sender, "ROOT_MENU")

        except Exception as e:
            logging.exception(f"[ERROR webhook]: {e}")

        return "ok", 200
