# app/utils.py
from __future__ import annotations

import logging
import json
import requests
from typing import Any, Dict, Tuple, Optional, Iterable

from .config import (
    ACCESS_TOKEN,
    GRAPH_URL,
    ADMIN_NUMBERS,
    USE_TEMPLATES,
    ADMIN_TEMPLATE_NAME,
    ADMIN_TEMPLATE_LANG,
)

log = logging.getLogger(__name__)

# ── Simple in-memory error counters (per process) ─────────────────────────────
_ERROR_COUNTERS: Dict[str, int] = {}

def _bump(key: str) -> None:
    _ERROR_COUNTERS[key] = _ERROR_COUNTERS.get(key, 0) + 1

def get_error_counters() -> Dict[str, int]:
    return dict(_ERROR_COUNTERS)

# ──────────────────────────────────────────────────────────────────────────────
# Low-level HTTP
# ──────────────────────────────────────────────────────────────────────────────

def _headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

def wa_post(payload: Dict[str, Any]) -> Tuple[bool, int, Any]:
    """
    POST to WhatsApp Cloud API /messages.
    Returns (ok, status_code, response_json_or_text).
    """
    try:
        resp = requests.post(GRAPH_URL, headers=_headers(), json=payload, timeout=20)
        content_type = resp.headers.get("Content-Type", "")
        body: Any = resp.json() if "application/json" in content_type else resp.text
        ok = 200 <= resp.status_code < 300
        if not ok:
            # Count by family and specific code if present
            fam = f"wa_{resp.status_code // 100}xx"
            _bump(fam)
            code = None
            if isinstance(body, dict):
                try:
                    code = int(body.get("error", {}).get("code"))
                    _bump(f"wa_code_{code}")
                except Exception:
                    pass
            log.error("WA send failed %s: %s", resp.status_code, body)
        return ok, resp.status_code, body
    except Exception as e:
        _bump("wa_exception")
        log.exception("wa_post failed")
        return False, 599, str(e)

def _extract_error_code(resp: Any) -> Optional[int]:
    try:
        return int(resp.get("error", {}).get("code"))
    except Exception:
        return None

# ──────────────────────────────────────────────────────────────────────────────
# Inbound helpers
# ──────────────────────────────────────────────────────────────────────────────

def extract_message(data: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """
    Normalizes the incoming webhook into {'from': wa_id, 'body': text}.
    Returns None if not a text message.
    """
    try:
        entry = data["entry"][0]
        change = entry["changes"][0]
        value = change["value"]
        msgs = value.get("messages")
        if not msgs:
            return None
        msg = msgs[0]
        if msg.get("type") != "text":
            return None
        wa_from = msg.get("from")
        body = msg.get("text", {}).get("body", "")
        return {"from": wa_from, "body": body}
    except Exception:
        _bump("webhook_parse_error")
        log.exception("extract_message failed; data=%s", json.dumps(data, ensure_ascii=False)[:500])
        return None

def _normalize_wa(number: str) -> str:
    return number.replace("+", "").strip() if number else number

def is_admin(wa_number: str) -> bool:
    norm = _normalize_wa(wa_number)
    return any(_normalize_wa(a) == norm for a in ADMIN_NUMBERS)

# ──────────────────────────────────────────────────────────────────────────────
# Outbound helpers (with re-engagement fallback)
# ──────────────────────────────────────────────────────────────────────────────

def send_whatsapp_text(to: str, body: str) -> Tuple[bool, int, Any]:
    """
    Send freeform text. If outside the 24h window (error 131047),
    auto-fallback to the generic template (ADMIN_TEMPLATE_NAME) placing text in {{1}}.
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": _normalize_wa(to),
        "type": "text",
        "text": {"preview_url": False, "body": body},
    }
    ok, status, resp = wa_post(payload)
    if ok:
        return ok, status, resp

    code = _extract_error_code(resp) if isinstance(resp, dict) else None
    if code == 131047 and USE_TEMPLATES:
        tpl_name = ADMIN_TEMPLATE_NAME or "admin_update"
        tpl_lang = ADMIN_TEMPLATE_LANG or "en"
        log.info("[reengage] Fallback to template '%s' lang=%s for to=%s", tpl_name, tpl_lang, to)
        tok, tstatus, tresp = send_template(
            to=to,
            template=tpl_name,
            lang=tpl_lang,
            variables={"1": body},
        )
        return tok, tstatus, tresp

    return ok, status, resp

def send_template(
    to: str,
    template: str,
    lang: str,
    variables: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, int, Any]:
    params: list[Dict[str, Any]] = []
    if variables:
        keys = list(variables.keys())
        if all(isinstance(k, str) and k.isdigit() for k in keys):
            for k in sorted(keys, key=lambda x: int(x)):
                params.append({"type": "text", "text": str(variables[k])})
        elif set(keys) == {"name", "items"}:
            for k in ("name", "items"):
                params.append({"type": "text", "text": str(variables[k])})
        else:
            for k in keys:
                params.append({"type": "text", "text": str(variables[k])})

    payload = {
        "messaging_product": "whatsapp",
        "to": _normalize_wa(to),
        "type": "template",
        "template": {
            "name": template,
            "language": {"code": lang},
            "components": [{"type": "body", "parameters": params}],
        },
    }
    return wa_post(payload)

def send_whatsapp_buttons(
    to: str,
    body_text: str,
    buttons: Iterable[tuple[str, str]],
) -> Tuple[bool, int, Any]:
    btns = [{"type": "reply", "reply": {"id": bid, "title": title}} for bid, title in buttons]
    payload = {
        "messaging_product": "whatsapp",
        "to": _normalize_wa(to),
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {"buttons": btns[:3]},
        },
    }
    return wa_post(payload)
