# app/utils.py
"""
Utilities for WhatsApp Cloud API + routing helpers.
- extract_message(payload): parse inbound webhook JSON into a simple dict
- send_whatsapp_text(to, text): send plain text messages
- send_whatsapp_buttons(to, text, buttons): send interactive reply buttons
- send_whatsapp_template(to, template_name, lang_code, body_params): HSM/template sender
- send_admin_update(to_or_list, text): convenience wrapper for admin updates (uses template)
- is_admin(wa_number): check if a WA ID is an admin
"""

from __future__ import annotations
import logging
import requests
from typing import Any, Dict, List, Optional, Union

from . import config

log = logging.getLogger(__name__)

# --- Config / constants -------------------------------------------------------

ACCESS_TOKEN: str = config.ACCESS_TOKEN
PHONE_NUMBER_ID: str = config.PHONE_NUMBER_ID
GRAPH_URL: str = config.GRAPH_URL  # e.g. https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages

# Admin numbers: keep legacy single-admin alias for older code
ADMIN_NUMBERS: List[str] = config.ADMIN_NUMBERS or []
ADMIN_NUMBER: str = ADMIN_NUMBERS[0] if ADMIN_NUMBERS else ""

ADMIN_TEMPLATE_NAME: str = getattr(config, "ADMIN_TEMPLATE_NAME", "admin_update")
ADMIN_TEMPLATE_LANG: str = getattr(config, "ADMIN_TEMPLATE_LANG", "en")
USE_TEMPLATES: bool = bool(getattr(config, "USE_TEMPLATES", False))

# --- Helpers ------------------------------------------------------------------

def is_admin(wa_number: str) -> bool:
    """Return True if the WA number is configured as an admin."""
    return (wa_number or "").strip() in ADMIN_NUMBERS


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

        body_text: str = ""
        btn_id: Optional[str] = None

        if mtype == "text":
            body_text = (msg.get("text", {}) or {}).get("body", "")

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
                body_text = ""

        elif mtype == "button":
            button = msg.get("button", {}) or {}
            btn_id = button.get("payload")
            body_text = button.get("text") or ""

        else:
            body_text = (msg.get("text", {}) or {}).get("body", "")

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


# --- HTTP helpers -------------------------------------------------------------

def _headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def safe_json(r: requests.Response) -> Any:
    try:
        return r.json()
    except Exception:
        return {"text": r.text[:500]}


# --- Senders ------------------------------------------------------------------

def send_whatsapp_text(to: str, text: str) -> Dict[str, Any]:
    """
    Send a plain text WhatsApp message via Cloud API.
    NOTE: This will FAIL outside the 24h window. Use templates for re-engagement.
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


def send_whatsapp_template(
    to: str,
    template_name: str,
    lang_code: str,
    body_params: List[str] | None = None,
) -> Dict[str, Any]:
    """
    Send a pre-approved template message (HSM).
    body_params: list of strings to fill {{1}}, {{2}}, ... in the BODY component.
    """
    if not to:
        raise ValueError("Recipient 'to' is required")
    body_params = body_params or []

    components: List[Dict[str, Any]] = []
    if body_params:
        components.append({
            "type": "body",
            "parameters": [{"type": "text", "text": str(v)[:1024]} for v in body_params]
        })

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": lang_code},
            "components": components if components else [],
        },
    }

    try:
        r = requests.post(GRAPH_URL, headers=_headers(), json=payload, timeout=15)
        if r.status_code >= 400:
            log.error("WA template send failed %s: %s", r.status_code, r.text)
        return {"status_code": r.status_code, "response": safe_json(r)}
    except Exception:
        log.exception("Error sending WhatsApp template")
        return {"status_code": 0, "response": None}


def send_admin_update(to_or_list: Union[str, List[str]], text: str) -> int:
    """
    Send admin update using pre-approved template (avoids 24h failure).
    Uses config.ADMIN_TEMPLATE_NAME and ADMIN_TEMPLATE_LANG.
    Returns number of attempts (success not guaranteed by API).
    """
    targets: List[str] = []
    if isinstance(to_or_list, list):
        targets = [t for t in to_or_list if t]
    elif isinstance(to_or_list, str) and to_or_list:
        targets = [to_or_list]
    elif ADMIN_NUMBERS:
        targets = ADMIN_NUMBERS

    sent = 0
    for t in targets:
        res = send_whatsapp_template(
            t,
            template_name=ADMIN_TEMPLATE_NAME,
            lang_code=ADMIN_TEMPLATE_LANG,
            body_params=[text],
        )
        sent += 1 if res.get("status_code", 0) > 0 else 0
    return sent
