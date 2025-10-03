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


def send_whatsapp_flow(to: str, flow_id: str, flow_cta: str = "Fill Form", prefill: dict | None = None) -> dict:
    """
    Send a WhatsApp interactive Flow message.
    """
    action_params = {
        "flow_id": flow_id,
        "flow_cta": flow_cta,
        "flow_message_version": "3",
    }
    if prefill:
        action_params["flow_action_payload"] = {"screen_0": prefill}

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "flow",
            "header": {"type": "text", "text": "New Client Registration"},
            "body": {"text": "Please complete this form to register a new client."},
            "footer": {"text": "PilatesHQ"},
            "action": {"name": "flow", "parameters": action_params},
        },
    }

    ok, status, body = _send_to_meta(payload)
    return {"ok": ok, "status_code": status, "response": body}


def send_whatsapp_button(to: str, text: str, buttons: list[dict]) -> dict:
    """
    Send a WhatsApp interactive button message.
    Example:
        send_whatsapp_button("2773...", "Confirm?", [
            {"id": "reject_123", "title": "❌ Reject"}
        ])
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": text},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": b["id"], "title": b["title"]}}
                    for b in buttons
                ]
            },
        },
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
    """
    try:
        result = func(*args, **kwargs)
        logger.info(f"[SAFE EXEC OK] {label} → {result}")
        return result
    except Exception as e:
        logger.exception(f"[SAFE EXEC FAIL] {label} args={args} kwargs={kwargs}: {e}")
        return None
