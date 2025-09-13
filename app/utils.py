# app/utils.py
"""
Utilities for WhatsApp Cloud API + routing helpers.
- extract_message(payload): parse inbound webhook JSON into a simple dict
- send_whatsapp_text(to, text): send plain text messages
- send_whatsapp_buttons(to, text, buttons): send interactive reply buttons
- is_admin(wa_number): check if a WA ID is an admin
"""

from __future__ import annotations
import logging
import requests
from typing import Any, Dict, List, Optional

from . import config

log = logging.getLogger(__name__)

# --- Config / constants -------------------------------------------------------

ACCESS_TOKEN: str = config.ACCESS_TOKEN
PHONE_NUMBER_ID: str = config.PHONE_NUMBER_ID
GRAPH_URL: str = config.GRAPH_URL  # e.g. https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages

# Admin numbers: keep legacy single-admin alias for older code
ADMIN_NUMBERS: List[str] = config.ADMIN_NUMBERS or []
ADMIN_NUMBER: str = ADMIN_NUMBERS[0] if ADMIN_NUMBERS else ""

# --- Helpers ------------------------------------------------------------------

def is_admin(wa_number: str) -> bool:
    """Return True if the WA number is configured as an admin."""
    return (wa_number or "").strip() in ADMIN_NUMBERS


def _first(d: Dict, key: str, default=None):
    v = d.get(key, default)
    return v


def extract_message(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Normalise WhatsApp webhook payload into:
      {
        "from": "<wa_id>",
        "id": "<message_id>",
        "type": "<text|interactive|button|other>",
        "body": "<text or button title>",
        "btn_id": "<reply id>" (optional),
      }
    Returns None if no message found (e.g., status updates only).
    """
    try:
        if not payload or "entry" not in payload:
            return None

        # WhatsApp webhook structure: entry -> changes -> value -> messages[0]
        entries = payload.get("entry", [])
        if not entries:
            return None
        changes = entries[0].get("changes", [])
        if not changes:
            return None
        value = changes[0].get("value", {})
        messages = value.get("messages", [])
        if not messages:
            return None

        msg = messages[0]
        wa_from = msg.get("from")
        msg_id = msg.get("id")
        mtype = msg.get("type", "text")

        # Default body
        body_text: str = ""
        btn_id: Optional[str] = None

        # Text message
        if mtype == "text":
            body_text = (msg.get("text", {}) or {}).get("body", "")

        # Interactive messages (reply buttons or lists)
        elif mtype == "interactive":
            interactive = msg.get("interactive", {}) or {}
            itype = interactive.get("type")
            if itype == "button":
                reply = (interactive.get("button_reply") or interactive.get("nfm_reply") or {})
                btn_id = reply.get("id")
                body_text = reply.get("title") or ""
            elif itype == "list_reply":
                reply = interactive.get("list_reply") or {}
                btn_id = reply.get("id")
                body_text = reply.get("title") or reply.get("description") or ""
            else:
                body_text = ""  # unknown interactive subtype

        # Button (older payloads may surface type='button')
        elif mtype == "button":
            # Some webhooks use 'button' with 'text' as title and 'payload' as id
            button = msg.get("button", {}) or {}
            btn_id = button.get("payload")
            body_text = button.get("text") or ""

        else:
            # Fallback: try text->body if present
            body_text = (msg.get("text", {}) or {}).get("body", "")

        # Normalise casing/whitespace at the router level if needed
        return {
            "from": wa_from,
            "id": msg_id,
            "type": mtype,
            "body": body_text.strip(),
            "btn_id": btn_id,
        }

    except Exception:
        log.exception("Failed to extract message from webhook payload")
        return None


# --- Sending messages ---------------------------------------------------------

def _headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def send_whatsapp_text(to: str, text: str) -> Dict[str, Any]:
    """
    Send a plain text WhatsApp message via Cloud API.
    """
    if not to:
        raise ValueError("Recipient 'to' is required")

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"preview_url": False, "body": text[:4096]},
    }

    try:
        r = requests.post(GRAPH_URL, headers=_headers(), json=payload, timeout=15)
        if r.status_code >= 400:
            log.error("WA text send failed %s: %s", r.status_code, r.text)
        return {"status_code": r.status_code, "response": safe_json(r)}
    except Exception:
        log.exception("Error sending WhatsApp text")
        return {"status_code": 0, "response": None}


def send_whatsapp_buttons(to: str, text: str, buttons: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Send interactive reply buttons.
    buttons: list of {"id": "...", "title": "..."} (max 3 per WA spec).
    """
    if not to:
        raise ValueError("Recipient 'to' is required")
    if not buttons:
        raise ValueError("At least one button is required")

    # WA allows up to 3 reply buttons
    btns = []
    for b in buttons[:3]:
        bid = b.get("id")
        title = b.get("title")
        if not bid or not title:
            raise ValueError("Each button needs 'id' and 'title'")
        btns.append({"type": "reply", "reply": {"id": bid, "title": title[:20]}})

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": text[:1024]},
            "action": {"buttons": btns},
        },
    }

    try:
        r = requests.post(GRAPH_URL, headers=_headers(), json=payload, timeout=15)
        if r.status_code >= 400:
            log.error("WA buttons send failed %s: %s", r.status_code, r.text)
        return {"status_code": r.status_code, "response": safe_json(r)}
    except Exception:
        log.exception("Error sending WhatsApp buttons")
        return {"status_code": 0, "response": None}


def safe_json(r: requests.Response) -> Any:
    try:
        return r.json()
    except Exception:
        return {"text": r.text[:500]}
