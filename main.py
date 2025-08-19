from flask import Flask, request
import os
import logging

from booking import handle_booking_message
from wellness import handle_wellness_message
from utils import send_whatsapp_buttons

app = Flask(__name__)

# Env
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "your_verify_token_here")
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID")

# Logging
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, log_level))

@app.route("/", methods=["GET"])
def home():
    logging.info("Health check")
    return "PilatesHQ WhatsApp Bot is running!", 200

# Webhook verification (GET)
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    logging.info(f"[VERIFY] mode={mode} token={token}")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        logging.info("[VERIFY] success")
        return challenge, 200
    logging.warning("[VERIFY] failed")
    return "Forbidden", 403

# Webhook receiver (POST)
@app.route("/webhook", methods=["POST"])
def receive_webhook():
    data = request.get_json()
    logging.info(f"[INCOMING] {data}")

    try:
        value = data["entry"][0]["changes"][0]["value"]
        if "messages" not in value:
            return "ok", 200

        msg = value["messages"][0]
        sender = msg["from"]

        # Interactive button reply
        if msg.get("type") == "interactive":
            button_id = msg["interactive"]["button_reply"]["id"].strip().upper()
            logging.info(f"[CLICK] {sender} -> {button_id}")
            route_message(sender, button_id)
            return "ok", 200

        # Text message
        if msg.get("type") == "text":
            text = msg["text"]["body"].strip().upper()
            logging.info(f"[TEXT] {sender} -> {text}")
            route_message(sender, text)
            return "ok", 200

    except Exception as e:
        logging.error(f"[ERROR] webhook handling failed: {e}", exc_info=True)

    return "ok", 200

def route_message(sender: str, text: str):
    if text in ("MENU", "MAIN_MENU", "HI", "HELLO", "START"):
        logging.info(f"[FLOW] MAIN_MENU shown -> {sender}")
        send_main_menu(sender)
    elif text == "ABOUT":
        logging.info(f"[FLOW] ABOUT clicked -> {sender}")
        send_about(sender)
    elif text == "WELLNESS":
        logging.info(f"[FLOW] WELLNESS clicked -> {sender}")
        reply = handle_wellness_message("wellness", sender)
        send_whatsapp_buttons(sender, reply)
    elif text == "BOOK":
        logging.info(f"[FLOW] BOOK clicked -> {sender}")
        handle_booking_message("BOOK", sender)  # booking flow sends its own buttons
    else:
        # Default to wellness chat for free text
        reply = handle_wellness_message(text, sender)
        send_whatsapp_buttons(sender, reply)

def send_main_menu(to: str):
    send_whatsapp_buttons(
        to,
        "👋 Welcome to PilatesHQ! Please choose an option:",
        [
            {"id": "ABOUT", "title": "ℹ️ About PilatesHQ"},
            {"id": "WELLNESS", "title": "💬 Wellness Q&A"},
            {"id": "BOOK", "title": "📅 Book a Class"},
        ],
    )

def send_about(to: str):
    logging.info(f"[FLOW] ABOUT display -> {to}")
    send_whatsapp_buttons(
        to,
        "PilatesHQ delivers transformative Pilates sessions led by internationally certified instructors, "
        "emphasizing holistic wellness, enhanced strength, and improved mobility.\n"
        "📍 Norwood, Johannesburg • 🎉 Opening Special: Group Classes @ R180 until January",
        [{"id": "MENU", "title": "🏠 Return to Menu"}],
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
