# app/utils.py
import logging, requests, os

logger = logging.getLogger(__name__)

WHATSAPP_API_URL = "https://graph.facebook.com/v17.0/{phone_number_id}/messages"
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "")


def _send_to_meta(payload: dict) -> dict:
    """
    Low-level sender to Meta WhatsApp API.
    Returns a dict with ok, status_code, and response body.
    """
    url = WHATSAPP_API_URL.format(phone_number_id=PHONE_NUMBER_ID)
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        body = {}
        try:
            body = resp.json()
        except Exception:
            body = {"raw_text": resp.text[:500]}
        result = {
            "ok": resp.ok,
            "status_code": resp.status_code,
            "response": body,
        }
        if not resp.ok:
            logger.error("[MetaSendError] status=%s body=%s payload=%s",
                         resp.status_code, resp.text, payload)
        else:
            logger.info("WhatsApp API %s OK", resp.status_code)
        return result
    except Exception as e:
        logger.exception("[MetaSendException] payload=%s", payload)
        return {"ok": False, "status_code": 500, "response": {"error": str(e)}}


def send_whatsapp_template(to: str, name: str, lang: str, variables: list[str]) -> dict:
    """
    Send a WhatsApp template by name/language with body variables.
    Args:
        to: Target WhatsApp number in 27... format
        name: Template name (must be approved in Meta)
        lang: Language code (e.g. 'en_US')
        variables: List of strings mapped to {{1}}, {{2}}, etc.
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


def send_whatsapp_text(to: str, text: str) -> dict:
    """
    Fallback plain-text sender (not template).
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }
    return _send_to_meta(payload)

def normalize_wa(number: str) -> str:
    """
    Normalize WhatsApp numbers into international format (South Africa default).
    - Removes spaces, dashes, plus.
    - Converts leading 0 to 27 (South Africa country code).
    """
    if not number:
        return number
    n = str(number).replace(" ", "").replace("-", "").replace("+", "")
    if n.startswith("0"):
        n = "27" + n[1:]
    return n