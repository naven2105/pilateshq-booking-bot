from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional, Tuple
import requests

from .config import (
    ACCESS_TOKEN,
    GRAPH_URL,
    ADMIN_NUMBERS,
    TEMPLATE_LANG,  # default language preference from config (e.g., "en_ZA" or "en")
)

log = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# WhatsApp helpers
# -----------------------------------------------------------------------------

def _headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

def is_admin(wa_number: str) -> bool:
    """Return True if a WA number is in the configured admin list (accepts with or without leading '+')."""
    n = wa_number.strip().lstrip("+")
    return any(n == a.strip().lstrip("+") for a in ADMIN_NUMBERS)

def extract_message(payload: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """
    Extract a simple text message from the WhatsApp webhook payload.
    Returns: {"from": "<wa_id>", "body": "<text>"} or None if not a text message.
    Ignores 'statuses' callbacks.
    """
    try:
        entries = payload.get("entry", [])
        for entry in entries:
            changes = entry.get("changes", [])
            for ch in changes:
                value = ch.get("value", {})
                # ignore status webhooks
                if "statuses" in value:
                    continue
                msgs = value.get("messages", [])
                if not msgs:
                    continue
                msg = msgs[0]
                if msg.get("type") != "text":
                    return None
                return {"from": msg.get("from", ""), "body": msg.get("text", {}).get("body", "")}
    except Exception:
        log.exception("extract_message failed")
    return None

# -----------------------------------------------------------------------------
# Send: plain text
# -----------------------------------------------------------------------------

def send_whatsapp_text(to: str, text: str) -> Tuple[bool, int, Dict[str, Any]]:
    """
    Send a plain text WhatsApp message.
    Returns (ok, status_code, response_json)
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }
    r = requests.post(GRAPH_URL, headers=_headers(), json=payload, timeout=20)
    ok = r.status_code // 100 == 2
    if not ok:
        try:
            log.error("WA send failed %s: %s", r.status_code, r.json())
        except Exception:
            log.error("WA send failed %s (no json body)", r.status_code)
    return ok, r.status_code, _safe_json(r)

# -----------------------------------------------------------------------------
# Send: quick buttons (for simple menus)
# -----------------------------------------------------------------------------

def send_whatsapp_buttons(to: str, body_text: str, buttons: List[str]) -> Tuple[bool, int, Dict[str, Any]]:
    """
    Send 1–3 quick-reply buttons under a text message.
    """
    if not buttons:
        return send_whatsapp_text(to, body_text)

    # WhatsApp expects up to 3 button replies
    btns = []
    for idx, label in enumerate(buttons[:3], start=1):
        btns.append({
            "type": "reply",
            "reply": {"id": f"btn_{idx}", "title": label[:20]}  # WA UI truncates long titles; keep it short
        })

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {"buttons": [{"type": "reply", "reply": b["reply"]} for b in btns]},
        }
    }
    r = requests.post(GRAPH_URL, headers=_headers(), json=payload, timeout=20)
    ok = r.status_code // 100 == 2
    if not ok:
        try:
            log.error("WA buttons send failed %s: %s", r.status_code, r.json())
        except Exception:
            log.error("WA buttons send failed %s (no json body)", r.status_code)
    return ok, r.status_code, _safe_json(r)

# -----------------------------------------------------------------------------
# Send: template with language fallback
# -----------------------------------------------------------------------------

# Per-template preferred language order (most-preferred first).
# We’ll try these, then fall back to config.TEMPLATE_LANG, then common English variants.
PREFERRED_LANGS: Dict[str, List[str]] = {
    # Admin ops
    "admin_hourly_update": ["en_ZA", "en", "en_US"],
    "admin_20h00": ["en_ZA", "en", "en_US"],
    "admin_cancel_all_sessions_admin_sick_unavailable": ["en_ZA", "en", "en_US"],
    "admin_update": ["en", "en_US", "en_ZA"],

    # Client reminders
    "session_tomorrow": ["en_US", "en", "en_ZA"],
    "session_next_hour": ["en", "en_US", "en_ZA"],
    "weekly_template_message": ["en", "en_US", "en_ZA"],
}

def send_whatsapp_template(
    to: str,
    template_name: str,
    params: Optional[List[str]] = None,
    lang_prefer: Optional[str] = None,
) -> Tuple[bool, int, Dict[str, Any], Optional[str]]:
    """
    Send a template message with robust language fallback.

    Args:
        to: recipient wa_id or phone (without +).
        template_name: Meta-approved template name.
        params: list of strings -> used as BODY parameters {{1}}, {{2}}, ...
        lang_prefer: optional explicit first-choice language (e.g., "en_ZA").

    Returns:
        (ok, status_code, response_json, chosen_language)
    """
    params = params or []
    # Build prioritized language chain without duplicates
    chain = []
    if lang_prefer:
        chain.append(lang_prefer)
    chain.extend(PREFERRED_LANGS.get(template_name, []))
    if TEMPLATE_LANG:
        chain.append(TEMPLATE_LANG)
    chain.extend(["en_ZA", "en_US", "en"])  # generic fallbacks

    # de-duplicate while preserving order
    seen = set()
    lang_chain = []
    for code in chain:
        if code and code not in seen:
            seen.add(code)
            lang_chain.append(code)

    # Try each language until one succeeds or we hit a non-translation error
    last_resp: Dict[str, Any] = {}
    last_status = 0
    for lang in lang_chain:
        payload = _template_payload(to, template_name, lang, params)
        r = requests.post(GRAPH_URL, headers=_headers(), json=payload, timeout=20)
        last_status = r.status_code
        last_resp = _safe_json(r)

        if r.status_code // 100 == 2:
            return True, r.status_code, last_resp, lang

        # If the error is "template not in this translation", continue fallback.
        err = (last_resp or {}).get("error", {})
        err_code = err.get("code")
        details = (err.get("error_data") or {}).get("details", "")
        if err_code == 132001 and "does not exist in" in str(details):
            log.warning("WA template missing in lang=%s (name=%s); trying fallback...", lang, template_name)
            continue

        # For parameter format issues or 24h window etc., don't keep trying.
        if err_code in (131047, 132018):
            log.error("WA send failed %s: %s", r.status_code, last_resp)
            return False, r.status_code, last_resp, lang

        # Unknown error: stop retrying to avoid rate noise
        log.error("WA send failed %s: %s", r.status_code, last_resp)
        return False, r.status_code, last_resp, lang

    # If we exhausted the chain
    log.error("WA template send failed for all languages (name=%s). last_status=%s resp=%s",
              template_name, last_status, last_resp)
    return False, last_status, last_resp, None

def _template_payload(to: str, template_name: str, language: str, params: List[str]) -> Dict[str, Any]:
    return {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language},
            "components": [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": _normalize_param(p)} for p in params],
                }
            ],
        },
    }

def _normalize_param(s: str) -> str:
    """
    WhatsApp template params cannot include newlines or tab characters,
    and cannot have 5+ consecutive spaces. Normalize lightly.
    """
    if s is None:
        return ""
    out = str(s).replace("\t", " ").replace("\n", " ").replace("\r", " ")
    while "     " in out:  # collapse 5+ spaces to 4
        out = out.replace("     ", "    ")
    return out.strip()

def _safe_json(r: requests.Response) -> Dict[str, Any]:
    try:
        return r.json()
    except Exception:
        return {}
