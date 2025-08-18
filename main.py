# main.py
from flask import Flask, request
import os

from booking import handle_booking_message
from wellness import handle_wellness_message
from utils import send_whatsapp_message, send_whatsapp_buttons

app = Flask(__name__)

# Environment variables
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "your_verify_token_here")
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

                            # Button clicks
                            if "interactive" in message:
                                button_reply = message["interactive"]["button_reply"]["id"]

                                if button_reply == "ABOUT":
                                    reply = "PilatesHQ is a boutique Pilates studio offering reformer and wall unit classes. We focus on wellness, strength, and flexibility in small groups."
                                elif button_reply == "WELLNESS":
                                    reply = handle_wellness_message("wellness", sender)
                                elif button_reply == "BOOK":
                                    reply = handle_booking_message("book", sender)
                                elif button_reply == "MENU":
                                    print("User returned to MENU")
                                    send_whatsapp_buttons(sender)  # back to main menu
                                    reply = None
                                else:
                                    reply = "Sorry, I didn’t understand that option."

                            # Free text messages
                            elif "text" in message:
                                msg_text = message["text"]["body"].strip().lower()
                                if any(word in msg_text for word in ["book", "schedule", "class"]):
                                    reply = handle_booking_message(msg_text, sender)
                                else:
                                    reply = handle_wellness_message(msg_text, sender)
                            else:
                                reply = "Unsupported message type."

                            # Only send text if reply is not None
                            if reply:
                                send_whatsapp_message(sender, reply)

        except Exception as e:
            print("Error processing webhook:", e)

    return "EVENT_RECEIVED", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
