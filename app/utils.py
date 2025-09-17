#app/utils.py
import logging, requests, os

logger = logging.getLogger(__name__)

WHATSAPP_API_URL = "https://graph.facebook.com/v17.0/{phone_number_id}/messages"
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "")

def _send_to_meta(payload: dict) -> tuple:
    url = WHATSAPP_API_URL.format(phone_number_id=PHONE_NUMBER_ID)
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        if not resp.ok:
            logger.error("[MetaSendError] status=%s body=%s payload=%s", resp.status_code, resp.text, payload)
        return resp.ok, resp.status_code, resp.json()
    except Exception as e:
        logger.exception("[MetaSendException] payload=%s", payload)
        return False, 500, {"error": str(e)}

def send_whatsapp_template(to: str, name: str, lang: str, variables: list[str]):
    """
    Send a WhatsApp template by name/language with body variables.
    """
    components = [{
        "type": "body",
        "parameters": [{"type": "text", "text": str(v)} for v in variables],
    }]

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": name,
            "language": {"code": lang},
            "components": components,
        },
    }
    return _send_to_meta(payload)
