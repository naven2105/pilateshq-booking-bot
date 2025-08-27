# app/router.py
import logging
import os
from flask import request

from .config import VERIFY_TOKEN
from .utils import normalize_wa
from .onboarding import handle_onboarding, capture_onboarding_free_text
from .admin import handle_admin_action


def register_routes(app):
    """Register webhook routes with the Flask app."""

    @app.route("/", methods=["GET"])
    def home():
        return "PilatesHQ Bot running", 200

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
        logging.debug(f"[WEBHOOK DATA keys] {list(data.keys())}")

        try:
            for entry in data.get("entry", []):
                for change in entry.get("changes", []):
                    value = (change.get("value") or {})

                    # Log and ignore status callbacks (sent, delivered, read, etc.)
                    if value.get("statuses"):
                        st = value["statuses"][0]
                        logging.info(f"[STATUS] id={st.get('id')} status={st.get('status')} to={st.get('recipient_id')}")
                        continue

                    for message in value.get("messages", []):
                        sender_raw = message.get("from", "")
                        sender = normalize_wa(sender_raw)  # '27...'

                        # ---- Admin check debug (for troubleshooting ENV/normalization) ----
                        env_admins = [n.strip() for n in os.getenv("ADMIN_WA_LIST", "").split(",") if n.strip()]
                        env_nadine = os.getenv("NADINE_WA", "").strip()
                        norm_admins = [normalize_wa(x) for x in env_admins]
                        norm_nadine = normalize_wa(env_nadine) if env_nadine else ""
                        is_admin_guess = sender in set(norm_admins + ([norm_nadine] if norm_nadine else []))
                        logging.debug(
                            f"[ADMIN CHECK] raw={sender_raw} norm={sender} admins={norm_admins} "
                            f"nadine={norm_nadine} is_admin={is_admin_guess}"
                        )
                        # --------------------------------------------------------------------

                        # Interactive replies (buttons / lists)
                        if "interactive" in message:
                            rep = message["interactive"]
                            reply_id = (
                                (rep.get("button_reply") or {}).get("id")
                                or (rep.get("list_reply") or {}).get("id")
                            )
                            logging.info(f"[USER CHOICE] {reply_id}")
                            if reply_id and reply_id.upper().startswith("ADMIN"):
                                handle_admin_action(sender, reply_id)
                            else:
                                handle_onboarding(sender, reply_id or "ROOT_MENU")
                            continue

                        # Plain text messages
                        if "text" in message:
                            msg_text = (message["text"].get("body") or "").strip()
                            up = msg_text.upper()
                            if up in ("HI", "HELLO", "START", "MENU", "MAIN_MENU"):
                                handle_onboarding(sender, "ROOT_MENU")
                            elif up.startswith("ADMIN"):
                                handle_admin_action(sender, up)
                            else:
                                # default: use onboarding free-text capture (e.g., name/medical/etc.)
                                capture_onboarding_free_text(sender, msg_text)
                            continue

        except Exception as e:
            logging.exception(f"[ERROR webhook]: {e}")

        return "ok", 200
