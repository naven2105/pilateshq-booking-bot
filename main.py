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

                            reply = None

                            # Case 1: Button replies
                            if "interactive" in message:
                                interactive = message["interactive"]
                                if interactive["type"] == "button_reply":
                                    button_id = interactive["button_reply"]["id"]

                                    if button_id == "ABOUT":
                                        reply = "ℹ️ PilatesHQ is a boutique studio in Lyndhurst. We focus on personalised Reformer Pilates for all clients, including rehabilitation and wellness support."
                                    elif button_id == "WELLNESS":
                                        reply = handle_wellness_message("wellness")
                                    elif button_id == "BOOK":
                                        reply = handle_booking_message("book")

                            # Case 2: Free text messages
                            elif "text" in message:
                                msg_text = message["text"]["body"].strip().lower()

                                if any(word in msg_text for word in ["book", "schedule", "class"]):
                                    reply = handle_booking_message(msg_text)
                                elif any(word in msg_text for word in ["hi", "hello", "menu", "start"]):
                                    # Show menu again
                                    send_whatsapp_buttons(sender)
                                else:
                                    reply = handle_wellness_message(msg_text)

                            # Send reply if we built one
                            if reply:
                                send_whatsapp_message(sender, reply)

        except Exception as e:
            print("Error processing webhook:", e)

    return "EVENT_RECEIVED", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
