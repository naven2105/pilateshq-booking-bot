import requests
import os

ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID")

WHATSAPP_API_URL = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"


def send_whatsapp_buttons(to: str, message_text: str = None, buttons: list = None):
    """
    Send WhatsApp interactive buttons.
    Automatically appends 'Return to Menu' button.
    """
    # Default message and buttons if not provided
    if message_text is None:
        message_text = "👋 Welcome to PilatesHQ! Please choose an option:"

    if buttons is None:
        buttons = [
            {"id": "ABOUT", "title": "ℹ️ About PilatesHQ"},
            {"id": "WELLNESS", "title": "💬 Wellness Q&A"},
            {"id": "BOOK", "title": "📅 Book a Class"},
        ]

    # Always add return-to-menu button
    if not any(btn["id"] == "MAIN_MENU" for btn in buttons):
        buttons.append({"id": "MAIN_MENU", "title": "🔙 Return to Menu"})

    # Convert to WhatsApp API format
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
            "action": {"buttons": whatsapp_buttons}
        }
    }
    response = requests.post(WHATSAPP_API_URL, headers=headers, json=data)
    print("Buttons sent:", response.status_code, response.text)
