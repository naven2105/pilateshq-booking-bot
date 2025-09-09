# app/utils.py
from __future__ import annotations

import logging
import re
import requests
from typing import List, Dict, Optional, Tuple

from .config import ACCESS_TOKEN, GRAPH_URL


def normalize_wa(s: str) -> str:
    if not s:
        return ""
    digits = re.sub(r"\D", "", s)
    # SA default +27 if starts with 0
    if digits.startswith("0"):
        digits = "27" + digits[1:]
    if digits.startswith("27"):
        return "+" + digits
    if digits.startswith("+"):
        return digits
    # already international?
    return "+" + digits if digits else ""


def _post_json(payload: dict) -> Tuple[int, dict]:
    try:
        resp = requests.post(
            GRAPH_URL,
            headers={
                "Authorization": f"Bearer {ACCESS_TOKEN}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=15,
        )
        code = resp.status_code
        data = {}
        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text}
        logging.info(f"[WA RESP {code}] {data}")
        return code, data
    except Exception as e:
        logging.exception("WhatsApp POST failed")
        return 0, {"error": str(e)}


def send_whatsapp_text(to: str, body: str) -> None:
    to = normalize_wa(to)
    if not to:
        return
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"preview_url": False, "body": body},
    }
    _post_json(payload)


def send_whatsapp_buttons(to: str, title: str, buttons: List[Dict[str, str]]) -> None:
    """
    Up to 3 reply buttons: [{"id": "MY_ID", "title": "My Button"}]
    """
    to = normalize_wa(to)
    if not to:
        return
    if not buttons:
        return send_whatsapp_text(to, title)

    # WhatsApp allows max 3 quick reply buttons
    btns = []
    for b in buttons[:3]:
        btns.append({
            "type": "reply",
            "reply": {
                "id": b["id"],
                "title": b["title"][:20],  # WA limits
            }
        })

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": title},
            "action": {"buttons": btns},
        },
    }
    _post_json(payload)
