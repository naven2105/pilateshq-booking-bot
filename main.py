# 🔹 main.py (Router / Orchestrator)
# Handles webhook verification (GET).
# Handles incoming WhatsApp messages (POST).
# Routes messages:
# Interactive button clicks → triggers:
# "ABOUT" → About PilatesHQ (static text).
# "WELLNESS" → Passes text to wellness.py (ChatGPT assistant).
# "BOOK" → Passes text to booking.py.
# Text messages:
# If contains book/schedule/class → goes to Booking.
# Otherwise → goes to Wellness Q&A.

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

                            # Handle text messages
                            if "text" in message:
                                msg_text = message["text"]["body"].strip().lower()

                                # Show menu if user greets
                                if msg_text in ["hi", "hello", "start"]:
                                    send_whatsapp_buttons(sender)
                                    continue

                                # Route normal text
                                if any(word in msg_text for word in ["book", "schedule", "class"]):
                                    reply = handle_booking_message(msg_text, sender)
                                else:
                                    reply = handle_wellness_message(msg_text)

                                send_whatsapp_message(sender, reply)

                            # Handle interactive button clicks
                            elif "interactive" in message:
                                button_reply = message["interactive"]["button_reply"]["id"]

                                if button_reply == "ABOUT":
                                    reply = (
                                        "ℹ️ *About PilatesHQ*\n\n"
                                        "PilatesHQ is a boutique studio in Lyndhurst, Johannesburg, "
                                        "specialising in Reformer Pilates for strength, mobility, and rehabilitation. "
                                        "We focus on personalised, small-group classes to help you move better and feel stronger."
                                    )
                                elif button_reply == "WELLNESS":
                                    reply = "💬 Great! Ask me anything about wellness, fitness, or Pilates."
                                elif button_reply == "BOOK":
                                    reply = handle_booking_message("book", sender)
                                else:
                                    reply = "Please choose one of the options from the menu."

                                send_whatsapp_message(sender, reply)

        except Exception as e:
            print("Error processing webhook:", e)

    return "EVENT_RECEIVED", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
