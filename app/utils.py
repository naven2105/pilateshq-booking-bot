# app/utils.py
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import requests

from .config import ACCESS_TOKEN, GRAPH_URL, ADMIN_NUMBERS

log = logging.getLogger(__name__)

# Simple in-memory error counters consumed by /diag/cron-status
ERROR_COUNTERS: Dict[str, int] = {
    "wa_template": 0,
    "wa_text": 0,
}

# ──────────────────────────────────────────────────────────────────────────────
# WhatsApp Cloud API – low-level helpers
# ──────────────────────────────────────────────────────────────────────────────

def _wa_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def _post_wa(payload: Dict[str, Any]) -> Tuple[bool, int, Dict[str, Any]]:
    """
    Perform the HTTP POST to Meta. Returns (ok, status_code, response_json_dict).
    Never raises; logs on failure.
    """
    try:
        resp = requests.post(GRAPH_URL, headers=_wa_headers(), data=json.dumps(payload), timeout=15)
        status = resp.status_code
        try:
            body = resp.json()
        except Exception:
            body = {"_raw": resp.text}
        ok = 200 <= status < 300 and "error" not in body
        if not ok:
            log.error("WA send failed %s: %s", status, body)
        return ok, status, body
    except Exception as e:
        log.exception("WA POST exception")
        return False, 0, {"error": {"message": str(e)}}


def _norm_err_code(j: Dict[str, Any]) -> Optional[str]:
    """
    Normalize Meta error code (int/string/list/dict) to a stable string for logging/counters.
    """
    err = j.get("error")
    if not isinstance(err, dict):
        return None
    code = err.get("code")
    try:
        if code is None:
            return None
        if isinstance(code, (list, dict)):
            return json.dumps(code, sort_keys=True)
        return str(code)
    except Exception:
        return "unknown"


# ──────────────────────────────────────────────────────────────────────────────
# Outbound senders
# ──────────────────────────────────────────────────────────────────────────────

def send_whatsapp_text(to: str, text: str) -> Dict[str, Any]:
    """
    Send a simple text message. Returns dict with keys: ok, status_code, response.
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }
    ok, status, body = _post_wa(payload)
    if not ok:
        ERROR_COUNTERS["wa_text"] = ERROR_COUNTERS.get("wa_text", 0) + 1
        code = _norm_err_code(body)
        if code:
            log.warning("WA text error code=%s to=%s", code, to)
    return {"ok": ok, "status_code": status, "response": body}


def send_whatsapp_template(to: str, name: str, lang: str = "en_US", variables: List[str] = None) -> Dict[str, Any]:
    """
    Send a template by name/language with body variables (text only).
    Defaults to English (US) templates.
    """
    if variables is None:
        variables = []

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

    ok, status, body = _post_wa(payload)
    if not ok:
        ERROR_COUNTERS["wa_template"] = ERROR_COUNTERS.get("wa_template", 0) + 1
        code = _norm_err_code(body)
        if code:
            log.warning("WA template send failed code=%s name=%s lang=%s to=%s", code, name, lang, to)
        else:
            log.warning("WA template send failed name=%s lang=%s to=%s", name, lang, to)

    return {"ok": ok, "status_code": status, "response": body}

def send_whatsapp_buttons(to: str, body_text: str, buttons: List[Tuple[str, str]]) -> Dict[str, Any]:
    """
    Optional: interactive reply buttons.
    buttons: list of (id, title)
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {"buttons": [
                {"type": "reply", "reply": {"id": bid, "title": title}}
                for bid, title in buttons
            ]},
        },
    }
    ok, status, body = _post_wa(payload)
    if not ok:
        ERROR_COUNTERS["wa_text"] = ERROR_COUNTERS.get("wa_text", 0) + 1
        code = _norm_err_code(body)
        if code:
            log.warning("WA buttons error code=%s to=%s", code, to)
    return {"ok": ok, "status_code": status, "response": body}


# ──────────────────────────────────────────────────────────────────────────────
# Inbound helpers
# ──────────────────────────────────────────────────────────────────────────────

def extract_message(data: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """
    Extract first text message {from, body} from a WhatsApp webhook payload.
    Returns None if not found.
    """
    try:
        entry = data.get("entry", [])[0]
        change = entry.get("changes", [])[0]
        value = change.get("value", {})
        msgs = value.get("messages", [])
        if not msgs:
            return None
        m = msgs[0]
        if m.get("type") != "text":
            return None
        return {"from": m.get("from"), "body": m.get("text", {}).get("body", "").strip()}
    except Exception:
        return None


def is_admin(wa_number: str) -> bool:
    """
    Basic admin check against configured list.
    Accept either with or without leading '+'.
    """
    if not wa_number:
        return False
    n = wa_number.strip()
    if n.startswith("+"):
        n = n[1:]
    return n in {a.lstrip("+") for a in ADMIN_NUMBERS}
