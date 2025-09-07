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
    Normalize a South African number to WhatsApp E.164 without '+' (as Meta accepts both).
    Examples:
      "0620469153"      -> "27620469153"
      "+27 62 046 9153" -> "27620469153"
      "27-62-046-9153"  -> "27620469153"
    If the number appears already international (starts with 27 or +27), keep it.
    Returns None if input is missing/empty.
    """
    if not raw:
        return None
    s = str(raw).strip()
    # Strip spaces and non-digits except leading '+'
    s = re.sub(r"[^\d+]", "", s)

    if s.startswith("+"):
        s = s[1:]  # Meta accepts without '+'

    # If it starts with '0' assume South Africa local -> replace with country code 27
    if s.startswith("0"):
        s = "27" + s[1:]

    # If it already starts with 27, keep as is
    # Otherwise, if it looks like an international number without country code, return as-is
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
    Perform the POST to WhatsApp Cloud API /messages.
    Returns (status_code, parsed_json_or_text).
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
    """
    Send a plain text message.
    """
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
    Reply to a specific incoming message by ID (keeps the chat thread clean).
    If `to` is provided, include it; otherwise Cloud API will route via context.
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
    Send a *template message*.
      - `components` should match Meta’s template component schema.
        Example for a single body variable:
          components=[{"type": "body", "parameters": [{"type": "text", "text": "09:00"}]}]
      - Language code defaults to TEMPLATE_LANG from config.
    """
    to_n = normalize_wa(to)
    if not to_n:
        return 0, "invalid recipient"

    lang = language_code or TEMPLATE_LANG
    payload: Dict[str, Any] = {
        "messaging_product": "whatsapp",
        "to": to_n,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": lang},
        },
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
    Send an interactive LIST message (admin pickers, etc.).

    `sections` format (Meta spec):
      sections = [
        {
          "title": "Optional Section Title",
          "rows": [
            {"id": "row_1_id", "title": "Row 1 Title", "description": "Optional desc"},
            {"id": "row_2_id", "title": "Row 2 Title"},
          ],
        },
        ...
      ]

    WhatsApp limits: up to 10 total rows across all sections; keep text short.
    """
    to_n = normalize_wa(to)
    if not to_n:
        return 0, "invalid recipient"

    interactive: Dict[str, Any] = {
        "type": "list",
        "body": {"text": body_text},
        "action": {
            "button": button_text,
            "sections": sections,
        },
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


# ─────────────────────────────────────────────────────────────────────────────
# Convenience: choose plain text vs. template based on config
# ─────────────────────────────────────────────────────────────────────────────

def send_admin_text_or_template(
    to: str,
    fallback_text: str,
    template_name: Optional[str] = None,
    template_components: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[int, Any]:
    """
    If USE_TEMPLATES is True and `template_name` is provided, send a template;
    otherwise send plain text.
    """
    if USE_TEMPLATES and template_name:
        return send_whatsapp_template(to, template_name, template_components)
    return send_whatsapp_text(to, fallback_text)
