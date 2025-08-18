#utils.py

def send_whatsapp_buttons(to: str, message_text: str = None, buttons: list = None):
    """
    Send WhatsApp interactive buttons.
    Always includes 'Return to Menu' as last button.
    """
    if message_text is None:
        message_text = "👋 Welcome to PilatesHQ! Please choose an option:"

    if buttons is None:
        buttons = [
            {"id": "ABOUT", "title": "ℹ️ About PilatesHQ"},
            {"id": "WELLNESS", "title": "💬 Wellness Q&A"},
            {"id": "BOOK", "title": "📅 Book a Class"},
        ]

    # Always add 'Return to Menu' if not present
    if not any(b["id"] == "MENU" for b in buttons):
        buttons.append({"id": "MENU", "title": "↩️ Return to Menu"})

    # Convert buttons to WhatsApp API format
    whatsapp_buttons = [
        {"type": "reply", "reply": {"id": b["id"], "title": b["title"]}}
        for b in buttons
    ]

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
