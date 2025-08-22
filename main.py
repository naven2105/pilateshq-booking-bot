from flask import Flask, request
import os
import logging

from booking import handle_booking_message
from wellness import handle_wellness_message
from utils import send_whatsapp_list
from db import init_db

app = Flask(__name__)

# Env
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "your_verify_token_here")

# Logging
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, log_level))

# ---- One-time DB init (Flask 3.x safe) ----
_db_inited = False

@app.before_request
def startup_db_once():
    global _db_inited
    if not _db_inited:
        try:
            init_db()
            logging.info("✅ DB initialised / verified")
        except Exception as e:
            logging.exception("❌ DB init failed", exc_info=True)
        _db_inited = True

# ---- Health check ----
@app.route("/", methods=["GET"])
def home():
    return "OK", 200

# ---- Webhook verification (GET) ----
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    mode = request.args.get("hub.mode")
    logging.info(f"[VERIFY] mode={mode}")
    if token == VERIFY_TOKEN:
        logging.info("[VERIFY] success")
        return challenge, 200
    logging.warning("[VERIFY] failed")
    return "Verification failed", 403

# ---- Webhook receiver (POST) ----
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

                    # Interactive replies (buttons/lists)
                    if message.get("type") == "interactive":
                        inter = message.get("interactive", {})
                        reply_id = ""
                        if "button_reply" in inter:
                            reply_id = inter["button_reply"]["id"]
                        elif "list_reply" in inter:
                            reply_id = inter["list_reply"]["id"]
                        reply_id = (reply_id or "").strip().upper()
                        logging.info(f"[CLICK] {sender} -> {reply_id}")
                        route_message(sender, reply_id)
                        continue

                    # Text messages
                    if message.get("type") == "text":
                        text = (message.get("text", {}).get("body") or "").strip().upper()
                        logging.info(f"[TEXT] {sender} -> {text}")
                        route_message(sender, text)
                        continue

    except Exception as e:
        logging.exception(f"[ERROR webhook]: {e}")

    return "ok", 200

# ---- Router ----
def route_message(sender: str, text: str):
    # Greetings / main menu
    if text in ("MENU", "MAIN_MENU", "HI", "HELLO", "START"):
        logging.info(f"[FLOW] INTRO_MENU -> {sender}")
        send_intro_and_menu(sender)
        return

    # Wellness flow
    if text == "WELLNESS" or text.startswith("WELLNESS_"):
        logging.info(f"[FLOW] WELLNESS -> {sender} | {text}")
        handle_wellness_message(text, sender)
        return

    # Booking flow
    if (
        text == "BOOK"
        or text in ("GROUP", "DUO", "SINGLE")
        or text.startswith(("DAY_", "TIME_", "PERIOD_"))
    ):
        logging.info(f"[FLOW] BOOK -> {sender} | {text}")
        handle_booking_message(text, sender)
        return

    # Default
    send_intro_and_menu(sender)

# ---- UI block ----
def send_intro_and_menu(recipient: str):
    intro = (
        "✨ Welcome to PilatesHQ ✨\n\n"
        "PilatesHQ delivers transformative Pilates sessions led by internationally certified instructors, "
        "emphasizing holistic wellness, enhanced strength, and improved mobility.\n"
        "📍 Norwood, Johannesburg • 🎉 Opening Special: Group Classes @ R180 until January\n"
        "🌐 https://pilateshq.co.za"
    )
    send_whatsapp_list(
        recipient,
        header="PilatesHQ",
        body=intro + "\n\nPlease choose an option:",
        button_id="MAIN_MENU",
        options=[
            {"id": "BOOK", "title": "📅 Book a Class"},
            {"id": "WELLNESS", "title": "💡 Wellness Tips"},
        ],
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
