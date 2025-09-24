import logging
import requests
import os

logger = logging.getLogger(__name__)

WHATSAPP_API_URL = "https://graph.facebook.com/v17.0/{phone_number_id}/messages"
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "")


def _send_to_meta(payload: dict) -> tuple:
    """
    Internal: send payload to Meta WhatsApp API.
    Returns (ok: bool, status_code: int, response_json: dict | str).
    """
    url = WHATSAPP_API_URL.format(phone_number_id=PHONE_NUMBER_ID)
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        try:
            body = resp.json()
        except Exception:
            body = resp.text
        ok = 200 <= resp.status_code < 300
        if not ok:
            logger.error(f"[WA SEND FAIL] status={resp.status_code} body={body}")
        return ok, resp.status_code, body
    except Exception as e:
        logger.exception("Failed to send payload to Meta")
        return False, 0, str(e)


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

    ok, status, body = _send_to_meta(payload)
    return {"ok": ok, "status_code": status, "response": body}


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
    ok, status, body = _send_to_meta(payload)
    return {"ok": ok, "status_code": status, "response": body}


def normalize_wa(num: str) -> str:
    """
    Normalise a WhatsApp number:
      - remove leading '+'
      - convert SA numbers '0xxxxxxxxx' → '27xxxxxxxxx'
    """
    if not num:
        return num
    num = num.strip().replace("+", "")
    if num.startswith("0"):
        num = "27" + num[1:]
    return num


def safe_execute(func, *args, label: str = "", **kwargs):
    """
    Wrapper to safely execute any function.
    Logs success/failure without breaking the bot flow.
    Example:
        safe_execute(send_whatsapp_text, wa, "Hello", label="welcome_prompt")
    """
    try:
        result = func(*args, **kwargs)
        logger.info(f"[SAFE EXEC OK] {label} → {result}")
        return result
    except Exception as e:
        logger.exception(f"[SAFE EXEC FAIL] {label} args={args} kwargs={kwargs}: {e}")
        return None
