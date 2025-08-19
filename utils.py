import requests
import os
import logging

ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID")

WHATSAPP_API_URL = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"

def send_whatsapp_buttons(to: str, message_text: str = None, buttons: list = None):
    """
    Send WhatsApp interactive buttons.
    """
    if message_text is None:
        message_text = "👋 Welcome to PilatesHQ! Please choose an option:"

    if buttons is None:
        buttons = [
            {"id": "ABOUT", "title": "ℹ️ About PilatesHQ"},
            {"id": "WELLNESS", "title": "💬 Wellness Q&A"},
            {"id": "BOOK", "title": "📅 Book a Class"},
        ]

    whatsapp_buttons = [{"type": "reply", "reply": {"id": b["id"], "title": b["title"]}} for b in buttons]

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
            "action": {"buttons": whatsapp_buttons}
        }
    }

    try:
        response = requests.post(WHATSAPP_API_URL, headers=headers, json=data)
        logging.info(f"Buttons sent to {to}: {response.status_code}, {response.text}")
    except Exception as e:
        logging.error(f"Error sending WhatsApp buttons to {to}: {e}", exc_info=True)
