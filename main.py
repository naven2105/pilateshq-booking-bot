from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

# Environment variables (configure in Render dashboard)
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "klresolute_verify_2025")
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID")

@app.route("/", methods=["GET"])
def home():
    return "PilatesHQ WhatsApp Bot is running!", 200

# --- Webhook Verification ---
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

# --- Handle Incoming Messages ---
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

                            if "text" in message:
                                msg_text = message["text"]["body"].strip().lower()
                                handle_message(sender, msg_text)

        except Exception as e:
            print("Error processing webhook:", e)

    return "EVENT_RECEIVED", 200

# --- Handle user message logic ---
def handle_message(sender, msg_text):
    if msg_text in ["hi", "hello", "menu"]:
        send_menu(sender)

    elif msg_text == "1":
        send_whatsapp_message(sender, "📅 To book a class, please reply with your preferred day & time.")
    elif msg_text == "2":
        send_whatsapp_message(sender, "🗓 PilatesHQ Schedule:\nMon-Fri: 7am, 9am, 5pm\nSat: 8am, 10am")
    elif msg_text == "3":
        send_whatsapp_message(sender, "🌱 Wellness Tip: Consistency is key! Even 10 minutes of Pilates daily can boost posture & energy.")
    else:
        send_whatsapp_message(sender, "🤖 Sorry, I didn’t understand that. Reply 'menu' to see options again.")

# --- Menu Message ---
def send_menu(to_number):
    menu_text = (
        "👋 Welcome to *PilatesHQ*!\n\n"
        "Please choose an option:\n"
        "1️⃣ Book a class\n"
        "2️⃣ View schedule\n"
        "3️⃣ Wellness tip\n\n"
        "Reply with the number of your choice."
    )
    send_whatsapp_message(to_number, menu_text)

# --- Send WhatsApp Message via Meta Cloud API ---
def send_whatsapp_message(to_number, message):
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": message}
    }
    response = requests.post(url, headers=headers, json=payload)
    print("Message sent:", response.status_code, response.text)
    return response

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
