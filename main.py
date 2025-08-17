from flask import Flask, request
import os

from booking import handle_booking_message
from wellness import handle_wellness_message
from utils import send_whatsapp_message, send_whatsapp_buttons

app = Flask(__name__)

# Environment variables
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "klresolute_verify_2025")
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID")


@app.route("/", methods=["GET"])
def home():
    return "PilatesHQ WhatsApp Bot is running!", 200


# Webhook verification for Meta
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode and token:
        if mode == "subscribe" and token == VERIFY_TOKEN:
            return challenge, 200
        else:
            return "Forbidden", 403
    return "Bad Request", 400


# Handle incoming WhatsApp messages
@app.route("/webhook", methods=["POST"])
def receive_webhook():
    data = request.get_json()

    if data and data.get("entry"):
        try:
            for entry in data["entry"]:
                for change in entry["changes"]:
                    if "messages" in change["value"]:
                        for message in change["value"]["messages"]:
                            sender = message["from"]

                            # If it's a button click
                            if message.get("type") == "button":
                                button_payload = message["button"]["payload"]

                                if button_payload == "ABOUT":
                                    reply = (
                                        "ℹ️ *About PilatesHQ*\n\n"
                                        "PilatesHQ is a boutique Pilates studio in Lyndhurst, Gauteng. "
                                        "We specialise in Reformer Pilates for all levels — from beginners to rehabilitation clients. "
                                        "Come move, strengthen, and feel amazing!"
                                    )

                                elif button_payload == "WELLNESS":
                                    reply = handle_wellness_message("hi")  # starter for ChatGPT

                                elif button_payload == "BOOK":
                                    reply = handle_booking_message("")  # booking logic from booking.py

                                else:
                                    reply = "Sorry, I didn’t understand that option."

                                send_whatsapp_message(sender, reply)

                            # If it's a normal text message
                            elif message.get("type") == "text":
                                msg_text = message["text"]["body"].strip().lower()

                                # Show welcome buttons on "hi", "hello", "start"
                                if msg_text in ["hi", "hello", "start"]:
                                    send_whatsapp_buttons(
                                        sender,
                                        "👋 Welcome to PilatesHQ!\nPlease choose an option:",
                                        [
                                            {"id": "ABOUT", "title": "ℹ️ About PilatesHQ"},
                                            {"id": "WELLNESS", "title": "💬 Wellness Q&A"},
                                            {"id": "BOOK", "title": "📅 Book a Class"},
                                        ],
                                    )
                                elif any(word in msg_text for word in ["book", "schedule", "class"]):
                                    reply = handle_booking_message(msg_text)
                                    send_whatsapp_message(sender, reply)
                                else:
                                    reply = handle_wellness_message(msg_text)
                                    send_whatsapp_message(sender, reply)

        except Exception as e:
            print("Error processing webhook:", e)

    return "EVENT_RECEIVED", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
