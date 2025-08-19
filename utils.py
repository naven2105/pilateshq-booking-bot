import requests
import os
import logging

ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID")

WHATSAPP_API_URL = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"


def send_whatsapp_list(recipient, header, body, button_id, options):
    """
    Send a WhatsApp list template.
    options must be <= 10 items due to WA API limit.
    """
    logging.info(f"[SEND LIST] To: {recipient}, Header: {header}, Body: {body}, Options: {len(options)}")

    if len(options) > 10:
        logging.warning("[UI ERROR] Too many options provided. Trimming to 10.")
        options = options[:10]

    rows = [{"id": opt["id"], "title": opt["title"]} for opt in options]

    payload = {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": header},
            "body": {"text": body},
            "footer": {"text": "Powered by PilatesHQ"},
            "action": {
                "button": "Choose",
                "sections": [
                    {
                        "title": "Options",
                        "rows": rows
                    }
                ]
            }
        }
    }

    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    response = requests.post(WHATSAPP_API_URL, headers=headers, json=payload)
    logging.debug(f"[WA RESP CODE] {response.status_code}")
    logging.debug(f"[WA RESP BODY] {response.text}")
    return response.json()
