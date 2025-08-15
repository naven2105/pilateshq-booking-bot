from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

# Environment variables (store these in Render's dashboard)
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
                            msg_text = message["text"]["body"]
                            send_whatsapp_message(sender, f"Echo: {msg_text}")
        except Exception as e:
            print("Error processing webhook:", e)

    return "EVENT_RECEIVED", 200

# Send WhatsApp message via Meta Cloud API
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
