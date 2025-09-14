# app/utils.py
from __future__ import annotations

import logging
import requests
from datetime import datetime
from typing import Dict, Tuple, Optional, List, Any

from .config import (
    ACCESS_TOKEN,
    GRAPH_URL,
    ADMIN_NUMBERS,
)

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Lightweight Observability (read by /diag/cron-status)
# ──────────────────────────────────────────────────────────────────────────────
LAST_RUN: Dict[str, str] = {}        # e.g. {"admin-notify":"2025-09-14T20:00:00Z"}
ERROR_COUNTERS: Dict[str, int] = {}  # e.g. {"wa_template": 3, "wa_text": 1, "wa_template_retry": 2}

def _now_iso() -> str:
    # Keep it UTC + 'Z' for clarity
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"

def stamp(name: str, extra: Optional[Dict[str, Any]] = None) -> None:
    """
    Record a 'last run' moment for a job/route.
    """
    LAST_RUN[name] = _now_iso()

def incr_error(bucket: str, inc: int = 1) -> None:
    ERROR_COUNTERS[bucket] = ERROR_COUNTERS.get(bucket, 0) + inc

# ──────────────────────────────────────────────────────────────────────────────
# WhatsApp helpers
# ──────────────────────────────────────────────────────────────────────────────
def _auth_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

def _normalize_msisdn(n: str) -> str:
    # Accepts "2773..." or "+2773..."; returns digits only (Cloud API accepts without '+')
    return n.replace("+", "").strip()

def is_admin(wa_number: str) -> bool:
    me = _normalize_msisdn(wa_number)
    admin_norm = {_normalize_msisdn(n) for n in ADMIN_NUMBERS}
    return me in admin_norm

def extract_message(payload: dict) -> Optional[Dict[str, str]]:
    """
    Extract a user text message from WhatsApp webhook payload.
    Returns {"from": "<wa_id>", "body": "<text>"} or None for non-message events.
    """
    try:
        entry = payload.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        # Status-only webhooks (delivery/read) have no 'messages'
        messages = value.get("messages")
        if not messages:
            return None
        msg = messages[0]
        if msg.get("type") != "text":
            return None
        return {"from": msg.get("from"), "body": msg.get("text", {}).get("body", "")}
    except Exception:
        log.exception("extract_message failed")
        return None

# ──────────────────────────────────────────────────────────────────────────────
# Senders
# ──────────────────────────────────────────────────────────────────────────────
def send_whatsapp_text(to: str, body: str) -> Tuple[bool, int, dict]:
    """
    Basic text sender (inside 24h window).
    """
    to_norm = _normalize_msisdn(to)
    data = {
        "messaging_product": "whatsapp",
        "to": to_norm,
        "type": "text",
        "text": {"preview_url": False, "body": body},
    }
    resp = requests.post(GRAPH_URL, json=data, headers=_auth_headers(), timeout=15)
    ok = 200 <= resp.status_code < 300
    if not ok:
        incr_error("wa_text")
        try:
            log.error("WA send failed %s: %s", resp.status_code, resp.json())
            return False, resp.status_code, resp.json()
        except Exception:
            log.error("WA send failed %s: <non-JSON body>", resp.status_code)
            return False, resp.status_code, {"error": "non-json"}
    return True, resp.status_code, resp.json()

def _template_components_from_vars(variables: Dict[str, str]) -> List[Dict[str, str]]:
    """
    Convert dict of variables into WA 'parameters' list in the insertion order.
    Supports numeric keys ("1","2") or arbitrary names; order matters.
    """
    params: List[Dict[str, str]] = []
    keys = list(variables.keys())
    if all(k.isdigit() for k in keys):
        keys = sorted(keys, key=lambda k: int(k))
    for k in keys:
        params.append({"type": "text", "text": str(variables[k])})
    return [{"type": "body", "parameters": params}]

def _post_template(to_norm: str, template: str, lang_code: str, components: List[Dict[str, Any]]):
    data = {
        "messaging_product": "whatsapp",
        "to": to_norm,
        "type": "template",
        "template": {
            "name": template,
            "language": {"code": lang_code},
            "components": components,
        },
    }
    resp = requests.post(GRAPH_URL, json=data, headers=_auth_headers(), timeout=15)
    ok = 200 <= resp.status_code < 300
    payload = {}
    try:
        payload = resp.json()
    except Exception:
        pass
    return ok, resp.status_code, payload

def send_template(
    to: str,
    template: str,
    lang: str,
    variables: Dict[str, str],
) -> Tuple[bool, int, dict]:
    """
    Sends a template message using WA Cloud API with language fallback.
    Tries: requested lang, then en_US, en_ZA, en (skipping duplicates).
    Counters:
      - wa_template_retry increments if we had to try a fallback but succeeded.
      - wa_template increments only if ALL fallbacks fail.
    """
    to_norm = _normalize_msisdn(to)
    components = _template_components_from_vars(variables)

    # Build fallback list
    candidates = [lang]
    for alt in ["en_US", "en_ZA", "en"]:
        if alt not in candidates:
            candidates.append(alt)

    retry_needed = False
    last_status = 0
    last_payload: dict = {}

    for idx, lang_code in enumerate(candidates):
        ok, status, payload = _post_template(to_norm, template, lang_code, components)
        if ok:
            if idx > 0:
                incr_error("wa_template_retry")
                log.info("WA template recovered via fallback lang=%s name=%s to=%s", lang_code, template, to_norm)
            return True, status, payload

        # If it looks like a translation-missing error (132001), mark retry and continue
        err_code = None
        try:
            err_code = payload.get("error", {}).get("code")
        except Exception:
            pass

        if err_code == 132001:
            retry_needed = True
            last_status, last_payload = status, payload
            log.warning("WA template missing in lang=%s (name=%s); trying fallback...", lang_code, template)
            continue

        # Other errors: give up immediately and count as a failure
        incr_error("wa_template")
        try:
            log.error("WA template send failed %s: %s", status, payload or "<non-JSON>")
        except Exception:
            log.error("WA template send failed %s: <non-JSON body>", status)
        return False, status, payload or {"error": "non-json"}

    # Exhausted all fallbacks
    incr_error("wa_template")
    if retry_needed:
        log.error("WA template send failed after fallbacks; last_status=%s last_payload=%s", last_status, last_payload or "<non-JSON>")
    else:
        log.error("WA template send failed; no fallback applicable; last_status=%s last_payload=%s", last_status, last_payload or "<non-JSON>")
    return False, last_status or 500, last_payload or {"error": "template failed after fallbacks"}

def send_whatsapp_buttons(to: str, body: str, buttons: List[Dict[str, str]]) -> Tuple[bool, int, dict]:
    """
    Optional: interactive buttons (reply buttons).
    buttons = [{"id":"next_lesson","title":"Next lesson"}, ...]
    """
    to_norm = _normalize_msisdn(to)
    data = {
        "messaging_product": "whatsapp",
        "to": to_norm,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": b["id"], "title": b["title"]}}
                    for b in buttons
                ]
            },
        },
    }
    resp = requests.post(GRAPH_URL, json=data, headers=_auth_headers(), timeout=15)
    ok = 200 <= resp.status_code < 300
    if not ok:
        incr_error("wa_buttons")
        try:
            log.error("WA buttons failed %s: %s", resp.status_code, resp.json())
            return False, resp.status_code, resp.json()
        except Exception:
            log.error("WA buttons failed %s: <non-JSON body>", resp.status_code)
            return False, resp.status_code, {"error": "non-json"}
    return True, resp.status_code, resp.json()
