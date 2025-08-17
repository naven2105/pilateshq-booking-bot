import requests
import os

ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID")

WHATSAPP_API_URL = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"


def send_whatsapp_message(to: str, message: str):
    """
    Send a plain text WhatsApp message.
    """
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message}
    }
    response = requests.post(WHATSAPP_API_URL, headers=headers, json=data)
    print("Message sent:", response.status_code, response.text)


def send_whatsapp_buttons(to: str):
    """
    Send the main menu with 3 quick-reply buttons.
    """
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": "👋 Welcome to PilatesHQ! Please choose an option:"},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "about", "title": "ℹ️ About PilatesHQ"}},
                    {"type": "reply", "reply": {"id": "wellness", "title": "💬 Wellness Q&A"}},
                    {"type": "reply", "reply": {"id": "book", "title": "📅 Book a Class"}},
                ]
            }
        }
    }
    response = requests.post(WHATSAPP_API_URL, headers=headers, json=data)
    print("Buttons sent:", response.status_code, response.text)
