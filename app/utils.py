import logging
import requests
from .config import ACCESS_TOKEN, GRAPH_URL

def normalize_wa(raw: str) -> str:
    """Normalize SA numbers to +27…; accepts 0…, 27…, +27…"""
    if not raw:
        return ""
    n = str(raw).strip().replace(" ", "").replace("-", "")
    if n.startswith("+27"):
        return n
    if n.startswith("27"):
        return "+" + n
    if n.startswith("0"):
        return "+27" + n[1:]
    return n

def send_whatsapp_text(to: str, body: str):
    """Send a simple text. Returns (status_code, response_text)."""
    payload = {
        "messaging_product": "whatsapp",
        "to": normalize_wa(to),
        "type": "text",
        "text": {"body": body}
    }
    return _send_json(payload)

def send_whatsapp_list(to: str, header: str, body: str, button_id: str, options: list):
    """
    Send a list message. Returns (status_code, response_text).
    options: list of {"id": "...", "title": "...", "description": "...?"}
    Max 10 rows; title <= 24 chars.
    """
    rows = []
    for opt in options[:10]:
        rows.append({
            "id": opt["id"],
            "title": opt["title"][:24],
            "description": opt.get("description", "")[:72]
        })
    payload = {
        "messaging_product": "whatsapp",
        "to": normalize_wa(to),
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": header[:60]},
            "body": {"text": body[:1024]},
            "action": {
                "button": "Choose",
                "sections": [{"title": "Options", "rows": rows}]
            }
        }
    }
    return _send_json(payload)

def send_whatsapp_buttons(to: str, body: str, buttons: list):
    """
    Send button message. Returns (status_code, response_text).
    buttons: list of {"id": "...", "title": "..."}
    Max 3 buttons; title <= 20 chars.
    """
    btns = []
    for b in buttons[:3]:
        btns.append({
            "type": "reply",
            "reply": {"id": b["id"], "title": b["title"][:20]}
        })
    payload = {
        "messaging_product": "whatsapp",
        "to": normalize_wa(to),
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body[:1024]},
            "action": {"buttons": btns}
        }
    }
    return _send_json(payload)

def _send_json(payload: dict):
    """
    Low-level sender. Always returns a 2-tuple:
      (HTTP status code int, response text str)
    On exception, returns (0, f'error…').
    """
    try:
        headers = {
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }
        resp = requests.post(GRAPH_URL, headers=headers, json=payload, timeout=15)
        logging.info(f"[WA RESP {resp.status_code}] {resp.text}")
        return resp.status_code, resp.text
    except Exception as e:
        logging.exception(f"[WA SEND ERROR] {e}")
        return 0, f"exception: {e}"
