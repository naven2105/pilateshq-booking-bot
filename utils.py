# 🔹 utils.py (WhatsApp API Helper)
# send_whatsapp_message() → sends plain text replies.
# send_whatsapp_buttons() → sends interactive button menus.
# Default welcome menu has 3 options:
# ℹ️ About PilatesHQ
# 💬 Wellness Q&A
# 📅 Book a Class

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


def send_whatsapp_buttons(to: str, message_text: str = None, buttons: list = None):
    """
    Send WhatsApp interactive buttons.
    Can be called with just 'to' parameter for default menu,
    or with custom message_text and buttons.
    """
    if message_text is None:
        message_text = "👋 Welcome to PilatesHQ! Please choose an option:"

    if buttons is None:
        buttons = [
            {"id": "ABOUT", "title": "ℹ️ About PilatesHQ"},
            {"id": "WELLNESS", "title": "💬 Wellness Q&A"},
            {"id": "BOOK", "title": "📅 Book a Class"},
        ]

    whatsapp_buttons = []
    for button in buttons:
        whatsapp_buttons.append({
            "type": "reply",
            "reply": {
                "id": button["id"],
                "title": button["title"]
            }
        })

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
            "body": {"text": message_text},
            "action": {
                "buttons": whatsapp_buttons
            }
        }
    }
    response = requests.post(WHATSAPP_API_URL, headers=headers, json=data)
    print("Buttons sent:", response.status_code, response.text)


def send_welcome_menu(to: str):
    """
    Send the default PilatesHQ welcome menu (buttons).
    This can be called when a new user messages for the first time.
    """
    send_whatsapp_buttons(to)
