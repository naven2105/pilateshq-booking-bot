# app/utils.py
from __future__ import annotations
import re
import json
import logging
from typing import Any, Dict, List
import requests
from .config import ACCESS_TOKEN, GRAPH_URL

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def normalize_wa(wa: str) -> str:
    s = (wa or "").strip().replace(" ", "")
    s = re.sub(r"[^\d+]", "", s)
    if s.startswith("+"):
        s = s[1:]
    if s.startswith("0") and len(s) >= 10:
        return "27" + s[1:]
    return s

def _post_json(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        headers = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}
        resp = requests.post(GRAPH_URL, headers=headers, data=json.dumps(payload), timeout=20)
        status = resp.status_code
        body: Dict[str, Any] = {}
        try:
            body = resp.json() if resp.content else {}
        except ValueError:
            body = {"raw_text": (resp.text or "").strip()[:500]}
        result = {"status_code": status, **(body or {})}
        if status >= 400:
            logging.error("WhatsApp API %s: %s", status, result)
        else:
            logging.info("WhatsApp API %s OK", status)
        return result
    except Exception as e:
        logging.exception("WhatsApp API call failed")
        return {"status_code": -1, "error": str(e)}

# ─────────────────────────────────────────────
# Text
# ─────────────────────────────────────────────

def send_whatsapp_text(to_wa: str, text: str) -> Dict[str, Any]:
    to = normalize_wa(to_wa)
    payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text}}
    return _post_json(payload)

# ─────────────────────────────────────────────
# Templates
# ─────────────────────────────────────────────

def send_whatsapp_template(to_wa: str, template_name: str, params: list[str], lang: str = "en") -> Dict[str, Any]:
    """
    Send a pre-approved template to WhatsApp Cloud API.
    Example: send_whatsapp_template("27831234567", "session_next_hour", ["09:00"])
    """
    to = normalize_wa(to_wa)
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": lang},
            "components": [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": str(p)} for p in (params or [])],
                }
            ],
        },
    }
    return _post_json(payload)
