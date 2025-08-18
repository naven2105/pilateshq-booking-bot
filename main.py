from flask import Flask, request
import os

from booking import handle_booking_message
from wellness import handle_wellness_message
from utils import send_whatsapp_buttons

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
                    value = change["value"]

                    if "messages" in value:
                        for message in value["messages"]:
                            sender = message["from"]

                            # If message is a button reply
                            if message.get("type") == "interactive":
                                button_reply = message["interactive"]["button_reply"]["id"]

                                if button_reply == "ABOUT":
                                    reply = (
                                        "ℹ️ *About PilatesHQ*\n\n"
                                        "PilatesHQ offers personalised and group Reformer Pilates classes "
                                        "focused on strength, flexibility, and recovery. "
                                        "We help you move better, feel stronger, and recover faster."
                                    )
                                    send_whatsapp_buttons(sender, reply)

                                elif button_reply == "WELLNESS":
                                    reply = "💬 Please type your wellness or Pilates-related question."
                                    send_whatsapp_buttons(sender, reply)

                                elif button_reply == "BOOK":
                                    reply = handle_booking_message("book", sender)
                                    send_whatsapp_buttons(sender, reply)

                                elif button_reply == "MAIN_MENU":
                                    send_whatsapp_buttons(sender)  # default menu

                            else:
                                # If it's free text, route it
                                msg_text = message["text"]["body"].strip().lower()

                                if any(word in msg_text for word in ["book", "schedule", "class"]):
                                    reply = handle_booking_message(msg_text, sender)
                                    send_whatsapp_buttons(sender, reply)
                                else:
                                    reply = handle_wellness_message(msg_text)
                                    send_whatsapp_buttons(sender, reply)

        except Exception as e:
            print("Error processing webhook:", e)

    return "EVENT_RECEIVED", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
