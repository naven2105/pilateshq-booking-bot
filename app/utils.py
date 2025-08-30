# app/utils.py
"""
WhatsApp transport utilities and phone normalization.
Keeps Meta payload shapes in one place; the rest of the app calls these helpers.
"""

import logging
import requests
from .config import ACCESS_TOKEN, GRAPH_URL

def normalize_wa(raw: str) -> str:
    """
    Normalize SA numbers into +27 format.
    Accepts 0..., 27..., +27... and returns +27xxxxxxxxx.
    Leaves other countries untouched (best effort).
    """
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
    """Send a plain text message."""
    _send_json({
        "messaging_product": "whatsapp",
        "to": normalize_wa(to),
        "type": "text",
        "text": {"body": body}
    })

def send_whatsapp_list(to: str, header: str, body: str, button_id: str, options: list):
    """
    Send an interactive list (up to 10 rows).
    options: list of {"id": "...", "title": "...", "description": "...?"}
    WA UX shows a 'Choose' button under each message block when using lists/buttons.
    """
    rows = []
    for opt in options[:10]:
        rows.append({
            "id": opt["id"],
            "title": opt["title"][:24],             # WA constraint
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
    _send_json(payload)

def send_whatsapp_buttons(to: str, body: str, buttons: list):
    """
    Send up to 3 reply buttons.
    buttons: list of {"id": "...", "title": "..."}
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
    _send_json(payload)

def _send_json(payload: dict):
    """
    Low-level POST to WhatsApp Graph API with logging.
    Render logs will show status code & response body for traceability.
    """
    try:
        headers = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}
        resp = requests.post(GRAPH_URL, headers=headers, json=payload, timeout=15)
        logging.info(f"[WA RESP {resp.status_code}] {resp.text}")
    except Exception as e:
        logging.exception(f"[WA SEND ERROR] {e}")
