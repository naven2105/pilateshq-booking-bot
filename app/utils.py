# app/utils.py
from __future__ import annotations

import json
import logging
import re
import requests
from typing import Any, Dict, List, Optional, Tuple

from .config import (
    ACCESS_TOKEN,
    GRAPH_URL,
    USE_TEMPLATES,
    TEMPLATE_LANG,
    TPL_ADMIN_HOURLY,
    TPL_ADMIN_20H00,
    TPL_NEXT_HOUR,
    TPL_TOMORROW,
    TPL_ADMIN_CANCEL_ALL,
    TPL_ADMIN_UPDATE,
)

# ─────────────────────────────────────────────────────────────────────────────
# WhatsApp helpers
# ─────────────────────────────────────────────────────────────────────────────

def normalize_wa(raw: str | None) -> str:
    """
    Normalize SA numbers: accept '0XXXXXXXXX', '27XXXXXXXXX', '+27XXXXXXXXX'.
    Returns E.164 (+27...) or '' if invalid.
    """
    if not raw:
        return ""
    s = re.sub(r"\D+", "", raw)  # strip non-digits
    # Common SA patterns
    if s.startswith("0") and len(s) == 10:
        return "+27" + s[1:]
    if s.startswith("27") and len(s) == 11:
        return "+" + s
    if raw.startswith("+") and len(s) >= 10:
        return "+" + s
    return ""


def _headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def _post(payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    """
    Low-level sender. Returns (status_code, parsed_json or {}).
    """
    try:
        resp = requests.post(GRAPH_URL, headers=_headers(), data=json.dumps(payload), timeout=20)
        code = resp.status_code
        try:
            body = resp.json()
        except Exception:
            body = {"raw": resp.text}
        logging.info("[WA RESP %s] %s", code, json.dumps(body))
        return code, body
    except Exception as e:
        logging.exception("WhatsApp POST failed")
        return 0, {"error": str(e)}


def send_whatsapp_text(to_e164: str, body: str) -> Tuple[int, Dict[str, Any]]:
    """
    Send a plain text message to a number (inside 24h window).
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": to_e164,
        "type": "text",
        "text": {"body": body},
    }
    return _post(payload)


def reply_to_whatsapp(to_e164: str, body: str, reply_to_message_id: Optional[str] = None) -> Tuple[int, Dict[str, Any]]:
    """
    Reply to a specific inbound message by including WhatsApp 'context.message_id'.
    - If reply_to_message_id is provided, WA will thread this as a reply.
    - If omitted, behaves like a normal send.
    """
    payload: Dict[str, Any] = {
        "messaging_product": "whatsapp",
        "to": to_e164,
        "type": "text",
        "text": {"body": body},
    }
    if reply_to_message_id:
        payload["context"] = {"message_id": reply_to_message_id}
    return _post(payload)


def send_whatsapp_template(to_e164: str, template_name: str, components: Optional[List[Dict[str, Any]]] = None,
                           language_code: Optional[str] = None) -> Tuple[int, Dict[str, Any]]:
    """
    Send an approved template.
    components example:
      [{"type":"body","parameters":[{"type":"text","text":"09:00"}]}]
    """
    lang = language_code or TEMPLATE_LANG or "en"
    payload: Dict[str, Any] = {
        "messaging_product": "whatsapp",
        "to": to_e164,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": lang},
        },
    }
    if components:
        payload["template"]["components"] = components
    return _post(payload)


# Optional convenience wrappers if/when you toggle template mode
def send_admin_hourly_template(to_e164: str, summary_text: str) -> Tuple[int, Dict[str, Any]]:
    """
    Uses a simple 1-variable admin template (e.g., 'admin_hourly_update' with body '{{1}}').
    """
    comps = [{"type": "body", "parameters": [{"type": "text", "text": summary_text}]}]
    return send_whatsapp_template(to_e164, TPL_ADMIN_HOURLY, comps)


def send_admin_20h00_template(to_e164: str, summary_text: str) -> Tuple[int, Dict[str, Any]]:
    comps = [{"type": "body", "parameters": [{"type": "text", "text": summary_text}]}]
    return send_whatsapp_template(to_e164, TPL_ADMIN_20H00, comps)


def send_next_hour_template(to_e164: str, hhmm: str) -> Tuple[int, Dict[str, Any]]:
    comps = [{"type": "body", "parameters": [{"type": "text", "text": hhmm}]}]
    return send_whatsapp_template(to_e164, TPL_NEXT_HOUR, comps)


def send_tomorrow_template(to_e164: str, hhmm: str) -> Tuple[int, Dict[str, Any]]:
    comps = [{"type": "body", "parameters": [{"type": "text", "text": hhmm}]}]
    return send_whatsapp_template(to_e164, TPL_TOMORROW, comps)


def send_admin_cancel_all_template(to_e164: str, reason_text: str) -> Tuple[int, Dict[str, Any]]:
    comps = [{"type": "body", "parameters": [{"type": "text", "text": reason_text}]}]
    return send_whatsapp_template(to_e164, TPL_ADMIN_CANCEL_ALL, comps)


def send_admin_update_template(to_e164: str, free_text: str) -> Tuple[int, Dict[str, Any]]:
    comps = [{"type": "body", "parameters": [{"type": "text", "text": free_text}]}]
    return send_whatsapp_template(to_e164, TPL_ADMIN_UPDATE, comps)
