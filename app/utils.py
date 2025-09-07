# app/utils.py
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import requests

from .config import (
    ACCESS_TOKEN,
    GRAPH_URL,
    USE_TEMPLATES,
    TEMPLATE_LANG,
)

# ─────────────────────────────────────────────────────────────────────────────
# Phone normalization
# ─────────────────────────────────────────────────────────────────────────────

def normalize_wa(raw: Optional[str]) -> Optional[str]:
    """
    Normalize a South African number to E.164 without '+' (Meta accepts without '+').
    Examples:
      "0620469153"      -> "27620469153"
      "+27 62 046 9153" -> "27620469153"
      "27-62-046-9153"  -> "27620469153"
    Returns None if input is missing/empty.
    """
    if not raw:
        return None
    s = str(raw).strip()
    s = re.sub(r"[^\d+]", "", s)  # keep digits and optional leading '+'
    if s.startswith("+"):
        s = s[1:]
    if s.startswith("0"):
        s = "27" + s[1:]
    return s or None


# ─────────────────────────────────────────────────────────────────────────────
# Low-level sender
# ─────────────────────────────────────────────────────────────────────────────

def _wa_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def wa_post(payload: Dict[str, Any]) -> Tuple[int, Any]:
    """
    POST to WhatsApp Cloud API /messages. Returns (status_code, parsed_json_or_text).
    """
    try:
        resp = requests.post(GRAPH_URL, headers=_wa_headers(), data=json.dumps(payload), timeout=20)
        try:
            data = resp.json()
        except Exception:
            data = resp.text
        logging.info("[WA RESP %s] %s", resp.status_code, json.dumps(data) if isinstance(data, dict) else data)
        return resp.status_code, data
    except Exception as e:
        logging.exception("WhatsApp POST failed: %s", e)
        return 0, str(e)


# ─────────────────────────────────────────────────────────────────────────────
# High-level send helpers
# ─────────────────────────────────────────────────────────────────────────────

def send_whatsapp_text(to: str, body: str) -> Tuple[int, Any]:
    """Send a plain text message."""
    to_n = normalize_wa(to)
    if not to_n:
        return 0, "invalid recipient"
    payload = {
        "messaging_product": "whatsapp",
        "to": to_n,
        "type": "text",
        "text": {"body": body},
    }
    return wa_post(payload)


def reply_to_whatsapp(reply_to_id: str, body: str, to: Optional[str] = None) -> Tuple[int, Any]:
    """
    Reply to a specific incoming message by ID (keeps the chat thread tidy).
    If `to` provided, include it; otherwise Cloud API will route via context.
    """
    payload: Dict[str, Any] = {
        "messaging_product": "whatsapp",
        "context": {"message_id": reply_to_id},
        "type": "text",
        "text": {"body": body},
    }
    if to:
        to_n = normalize_wa(to)
        if not to_n:
            return 0, "invalid recipient"
        payload["to"] = to_n
    return wa_post(payload)


def send_whatsapp_template(
    to: str,
    template_name: str,
    components: Optional[List[Dict[str, Any]]] = None,
    language_code: Optional[str] = None,
) -> Tuple[int, Any]:
    """
    Send a template message.
    Example for a single body variable:
      components=[{"type": "body", "parameters": [{"type": "text", "text": "09:00"}]}]
    """
    to_n = normalize_wa(to)
    if not to_n:
        return 0, "invalid recipient"
    lang = language_code or TEMPLATE_LANG
    payload: Dict[str, Any] = {
        "messaging_product": "whatsapp",
        "to": to_n,
        "type": "template",
        "template": {"name": template_name, "language": {"code": lang}},
    }
    if components:
        payload["template"]["components"] = components
    return wa_post(payload)


def send_whatsapp_list(
    to: str,
    header_text: Optional[str],
    body_text: str,
    button_text: str,
    sections: List[Dict[str, Any]],
) -> Tuple[int, Any]:
    """
    Send an interactive LIST message.

    sections = [
      {
        "title": "Optional Section",
        "rows": [
          {"id": "row_1", "title": "Row 1", "description": "Optional"},
          {"id": "row_2", "title": "Row 2"},
        ],
      }
    ]
    """
    to_n = normalize_wa(to)
    if not to_n:
        return 0, "invalid recipient"

    interactive: Dict[str, Any] = {
        "type": "list",
        "body": {"text": body_text},
        "action": {"button": button_text, "sections": sections},
    }
    if header_text:
        interactive["header"] = {"type": "text", "text": header_text}

    payload = {
        "messaging_product": "whatsapp",
        "to": to_n,
        "type": "interactive",
        "interactive": interactive,
    }
    return wa_post(payload)


def send_whatsapp_buttons(
    to: str,
    body_text: str,
    buttons: List[Dict[str, str]],
    header_text: Optional[str] = None,
    footer_text: Optional[str] = None,
) -> Tuple[int, Any]:
    """
    Send an interactive BUTTONS message (Quick replies).
    buttons format (max 3):
      [
        {"id": "cancel_yes", "title": "Confirm"},
        {"id": "cancel_no",  "title": "Dismiss"}
      ]
    """
    to_n = normalize_wa(to)
    if not to_n:
        return 0, "invalid recipient"

    btns = [{"type": "reply", "reply": {"id": b["id"], "title": b["title"][:20]}} for b in buttons][:3]

    interactive: Dict[str, Any] = {
        "type": "button",
        "body": {"text": body_text},
        "action": {"buttons": btns},
    }
    if header_text:
        interactive["header"] = {"type": "text", "text": header_text}
    if footer_text:
        interactive["footer"] = {"text": footer_text}

    payload = {
        "messaging_product": "whatsapp",
        "to": to_n,
        "type": "interactive",
        "interactive": interactive,
    }
    return wa_post(payload)


# ─────────────────────────────────────────────────────────────────────────────
# Convenience: choose text vs template
# ─────────────────────────────────────────────────────────────────────────────

def send_admin_text_or_template(
    to: str,
    fallback_text: str,
    template_name: Optional[str] = None,
    template_components: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[int, Any]:
    """
    If USE_TEMPLATES is True and a template is provided, send template; else plain text.
    """
    if USE_TEMPLATES and template_name:
        return send_whatsapp_template(to, template_name, template_components)
    return send_whatsapp_text(to, fallback_text)
