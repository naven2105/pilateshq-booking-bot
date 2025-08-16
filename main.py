# pilateshq-booking-bot/
# │
# ├── main.py          # Flask entry point
# ├── booking.py       # Handles PilatesHQ booking & schedule logic
# ├── wellness.py      # Handles ChatGPT wellness/FAQ responses
# ├── utils.py         # Shared helpers (e.g. send_whatsapp_message)
# ├── requirements.txt # Dependencies
# ├── Procfile         # Render process definition
# └── README.md        # (optional)

# This way, main.py is always clean, and all the conversation logic lives in booking.py. 
# Render will run it the same way as before — no changes needed to deployment.
# Extend the modular setup with Booking + Wellness (ChatGPT). 
# This way, PilatesHQ bot can handle structured bookings and friendly Q&A wellness support

# User sends "1 ..." → handled as Business/Bookings
# User sends "2 ..." → handled by wellness.py (ChatGPT wellness assistant)
# Other text → just echoes back

# flask → for the web server
# requests → for sending messages to Meta Cloud API
# openai → needed for wellness.py (ChatGPT calls)
# gunicorn → production server that Render uses to run Flask apps

from flask import Flask, request
import os

from booking import handle_booking_message
from wellness import handle_wellness_message
from utils import send_whatsapp_message

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
                            msg_text = message["text"]["body"].strip().lower()

                            # Simple routing
                            if any(word in msg_text for word in ["book", "schedule", "class"]):
                                reply = handle_booking_message(msg_text)
                            else:
                                reply = handle_wellness_message(msg_text)

                            send_whatsapp_message(sender, reply)
        except Exception as e:
            print("Error processing webhook:", e)

    return "EVENT_RECEIVED", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
