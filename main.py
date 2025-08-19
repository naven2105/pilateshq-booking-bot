from flask import Flask, request
import os
import logging

from booking import handle_booking_message
from wellness import handle_wellness_message
from utils import send_whatsapp_buttons

app = Flask(__name__)

# Environment variables
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "your_verify_token_here")
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID")

# Setup logging
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, log_level))

@app.route("/", methods=["GET"])
def home():
    logging.info("Health check called.")
    return "PilatesHQ WhatsApp Bot is running!", 200

# Webhook verification
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    logging.info(f"Webhook verification attempt: mode={mode}, token={token}")

    if mode and token:
        if mode == "subscribe" and token == VERIFY_TOKEN:
            logging.info("Webhook verified successfully.")
            return challenge, 200
        else:
            logging.warning("Webhook verification failed.")
            return "Forbidden", 403
    return "Bad Request", 400

# Handle messages
@app.route("/webhook", methods=["POST"])
def receive_webhook():
    data = request.get_json()
    logging.info(f"Incoming webhook payload: {data}")

    if data and data.get("entry"):
        try:
            for entry in data["entry"]:
                for change in entry["changes"]:
                    if "messages" in change["value"]:
                        for message in change["value"]["messages"]:
                            sender = message["from"]
                            logging.info(f"Message received from {sender}: {message}")

                            if message.get("type") == "interactive":
                                button_reply = message["interactive"]["button_reply"]["id"]
                                logging.info(f"Button clicked: {button_reply}")

                                if button_reply == "ABOUT":
                                    reply = "ℹ️ PilatesHQ is a specialised Pilates Studio offering reformer and wall-unit sessions designed to improve strength, flexibility, and posture."
                                    send_whatsapp_buttons(sender, reply)
                                elif button_reply == "WELLNESS":
                                    reply = handle_wellness_message("wellness")
                                    send_whatsapp_buttons(sender, reply)
                                elif button_reply == "BOOK":
                                    reply = handle_booking_message("book", sender)
                                    send_whatsapp_buttons(sender, reply)

                            elif message.get("type") == "text":
                                msg_text = message["text"]["body"].strip().lower()
                                logging.info(f"Text message received: {msg_text}")
                                reply = handle_wellness_message(msg_text)
                                send_whatsapp_buttons(sender, reply)

        except Exception as e:
            logging.error(f"Error processing webhook: {e}", exc_info=True)

    return "EVENT_RECEIVED", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
