import os
import logging
import requests

ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID")
WHATSAPP_API_URL = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"

def _post_to_whatsapp(payload: dict, to: str, context: str):
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        logging.info(f"[WA SEND] -> {to} | context={context}")
        logging.debug(f"[WA PAYLOAD] {payload}")
        resp = requests.post(WHATSAPP_API_URL, headers=headers, json=payload, timeout=15)
        logging.info(f"[WA RESP] <- {to} | status={resp.status_code}")
        logging.debug(f"[WA RESP BODY] {resp.text}")
        return resp
    except Exception as e:
        logging.error(f"[WA ERROR] send to {to} failed: {e}", exc_info=True)

def send_whatsapp_buttons(to: str, message_text: str = None, buttons: list = None):
    """Send WhatsApp interactive buttons. Always appends 'Return to Menu'."""
    if message_text is None:
        message_text = "👋 Welcome to PilatesHQ! Please choose an option:"

    if buttons is None:
        buttons = [
            {"id": "ABOUT", "title": "ℹ️ About PilatesHQ"},
            {"id": "WELLNESS", "title": "💬 Wellness Q&A"},
            {"id": "BOOK", "title": "📅 Book a Class"},
        ]

    # Ensure Return to Menu exists
    if not any(b.get("id") in ("MENU", "MAIN_MENU") for b in buttons):
        buttons.append({"id": "MENU", "title": "🔙 Return to Menu"})

    wa_buttons = [{"type": "reply", "reply": {"id": b["id"], "title": b["title"]}} for b in buttons]

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": message_text},
            "action": {"buttons": wa_buttons},
        },
    }
    btn_ids = [b["reply"]["id"] for b in wa_buttons]
    _post_to_whatsapp(payload, to, context=f"buttons text_len={len(message_text)} ids={btn_ids}")
