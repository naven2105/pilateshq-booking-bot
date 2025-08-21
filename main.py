from flask import Flask, request
import os
import logging

from booking import handle_booking_message
from wellness import handle_wellness_message
from utils import send_whatsapp_list

app = Flask(__name__)

# Environment variables
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "your_verify_token_here")

# Setup logging
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, log_level))

@app.route("/", methods=["GET"])
def home():
    return "OK", 200

@app.route("/webhook", methods=["GET"])
def verify_webhook():
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if token == VERIFY_TOKEN:
        return challenge
    return "Verification failed"

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
                    msg_text = message.get("text", {}).get("body", "").strip().upper()

                    # Handle button or list replies
                    if "button" in message or "interactive" in message:
                        reply_id = (
                            message.get("button", {}).get("payload") or
                            message.get("interactive", {}).get("button_reply", {}).get("id") or
                            message.get("interactive", {}).get("list_reply", {}).get("id")
                        )
                        if reply_id:
                            logging.info(f"[USER CHOICE] {reply_id}")
                            if reply_id.startswith("BOOK"):
                                handle_booking_message(reply_id, sender)
                            elif reply_id.startswith("WELLNESS"):
                                handle_wellness_message(reply_id, sender)
                            else:
                                send_main_menu(sender)
                        continue

                    # First-time message
                    if msg_text in ["HI", "HELLO", "START"]:
                        send_about_message(sender)
                        continue

                    # Default
                    send_main_menu(sender)

    except Exception as e:
        logging.exception(f"[ERROR in webhook]: {str(e)}")

    return "ok", 200


def send_about_message(recipient):
    about_text = (
        "✨ Welcome to PilatesHQ ✨\n\n"
        "PilatesHQ delivers transformative Pilates sessions led by internationally certified instructors, "
        "emphasizing holistic wellness, enhanced strength, and improved mobility.\n\n"
        "🌐 Visit us online: https://pilateshq.co.za"
    )
    send_whatsapp_list(recipient, "About PilatesHQ", about_text, "MAIN_MENU", [
        {"id": "BOOK", "title": "📅 Book a Class"},
        {"id": "WELLNESS", "title": "💡 Wellness Tips"},
    ])


def send_main_menu(recipient):
    menu_text = "Please choose from the options below 👇"
    send_whatsapp_list(recipient, "Main Menu", menu_text, "MAIN_MENU", [
        {"id": "BOOK", "title": "📅 Book a Class"},
        {"id": "WELLNESS", "title": "💡 Wellness Tips"},
    ])
