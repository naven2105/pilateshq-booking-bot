# app/utils.py
from __future__ import annotations

import re
import json
import logging
from typing import Any, Dict, List, Optional
import requests

from .config import ACCESS_TOKEN, GRAPH_URL

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def normalize_wa(wa: str) -> str:
    s = (wa or "").strip().replace(" ", "")
    s = re.sub(r"[^\d+]", "", s)
    if s.startswith("+"):
        s = s[1:]
    if s.startswith("0") and len(s) >= 10:
        return "27" + s[1:]
    return s

def _post_json(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    POST to WhatsApp Cloud API. Always returns a dict with status_code and any parsed body.
    Logs 4xx/5xx and non-JSON bodies for easier triage.
    """
    try:
        headers = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}
        resp = requests.post(GRAPH_URL, headers=headers, data=json.dumps(payload), timeout=20)
        status = resp.status_code
        body: Dict[str, Any] = {}
        try:
            body = resp.json() if resp.content else {}
        except ValueError:
            # Non-JSON response
            text = (resp.text or "").strip()
            body = {"raw_text": text[:500]}
        result = {"status_code": status, **(body or {})}
        if status >= 400:
            logging.error("WhatsApp API %s: %s", status, result)
        else:
            logging.info("WhatsApp API %s OK", status)
        return result
    except Exception as e:
        logging.exception("WhatsApp API call failed")
        return {"status_code": -1, "error": str(e)}

# ──────────────────────────────────────────────────────────────────────────────
# Text
# ──────────────────────────────────────────────────────────────────────────────
def send_whatsapp_text(to_wa: str, text: str) -> Dict[str, Any]:
    to = normalize_wa(to_wa)
    payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text}}
    return _post_json(payload)

# ──────────────────────────────────────────────────────────────────────────────
# Buttons (interactive)
# ──────────────────────────────────────────────────────────────────────────────
def _slugify_id(s: str, max_len: int = 256) -> str:
    base = re.sub(r"\s+", "_", s.strip().lower())
    base = re.sub(r"[^a-z0-9_.-]", "", base)
    return base[:max_len] if base else "btn"

def _normalize_buttons(buttons: List[Any]) -> List[Dict[str, str]]:
    norm: List[Dict[str, str]] = []
    for item in buttons or []:
        if isinstance(item, str):
            title = item.strip(); bid = _slugify_id(title)
        elif isinstance(item, dict):
            title = (item.get("title") or item.get("text") or "").strip()
            bid = (item.get("id") or _slugify_id(title)).strip()
        else:
            continue
        if not title:
            continue
        if len(title) > 20:
            title = title[:20]
        norm.append({"type": "reply", "reply": {"id": bid or "btn", "title": title}})
        if len(norm) == 3:
            break
    return norm

def send_whatsapp_buttons(to_wa: str, body: str, buttons: List[Any]) -> Dict[str, Any]:
    to = normalize_wa(to_wa)
    actions = _normalize_buttons(buttons)
    if not actions:
        return send_whatsapp_text(to, body)
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {"type": "button", "body": {"text": body}, "action": {"buttons": actions}},
    }
    return _post_json(payload)

# ──────────────────────────────────────────────────────────────────────────────
# List (picker)
# ──────────────────────────────────────────────────────────────────────────────
def _normalize_list_rows(rows: List[Any]) -> List[Dict[str, Dict[str, str]]]:
    out: List[Dict[str, Dict[str, str]]] = []
    for item in rows or []:
        if isinstance(item, str):
            title = item.strip(); rid = _slugify_id(title); description = ""
        elif isinstance(item, dict):
            title = (item.get("title") or item.get("text") or "").strip()
            rid = (item.get("id") or _slugify_id(title)).strip()
            description = (item.get("description") or "").strip()
        else:
            continue
        if not title:
            continue
        row = {"id": rid or "row", "title": title}
        if description:
            row["description"] = description
        out.append({"type": "row", "row": row})
    return out

def send_whatsapp_list(to_wa: str, body: str, button_text: str, section_title: str, rows: List[Any]) -> Dict[str, Any]:
    to = normalize_wa(to_wa)
    norm_rows = _normalize_list_rows(rows)
    if not norm_rows:
        return send_whatsapp_text(to, body)
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": body},
            "action": {
                "button": button_text[:20] if button_text else "Select",
                "sections": [{"title": section_title[:24] if section_title else "Options",
                              "rows": [r["row"] for r in norm_rows]}],
            },
        },
    }
    return _post_json(payload)
