# app/utils.py
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Tuple

import requests

from .config import ACCESS_TOKEN, GRAPH_URL

# ──────────────────────────────────────────────────────────────────────────────
# Phone number normalization (South Africa defaults supported)
# Accepts: 0XXXXXXXXX, 27XXXXXXXXX, +27XXXXXXXXX, or already-international.
# Returns: +<country><number> (E.164-like) or empty string if invalid.
# ──────────────────────────────────────────────────────────────────────────────
def normalize_wa(raw: str | None) -> str:
    if not raw:
        return ""
    s = str(raw).strip()
    # keep leading '+' then digits; or just digits; drop all else
    if s.startswith("+"):
        s = "+" + re.sub(r"\D", "", s[1:])
    else:
        s = re.sub(r"\D", "", s)

    # SA common forms → +27...
    if s.startswith("0") and len(s) >= 10:
        # 0XXXXXXXXX -> +27XXXXXXXXX
        return "+27" + s[1:]
    if s.startswith("27"):
        return "+27" + s[2:]
    if s.startswith("+27"):
        return s

    # If already looks like +CC..., accept
    if s.startswith("+") and len(s) > 4:
        return s

    # Fallback: if it’s exactly 10 digits starting with 0, handled above.
    # Otherwise invalid.
    logging.warning(f"[normalize_wa] cannot normalize '{raw}' -> '{s}'")
    return ""


# ──────────────────────────────────────────────────────────────────────────────
# Low-level HTTP helper to WhatsApp Cloud API
# Returns (status_code, parsed_json_or_text)
# ──────────────────────────────────────────────────────────────────────────────
def _wa_post(payload: Dict[str, Any]) -> Tuple[int, Any]:
    if not ACCESS_TOKEN or not GRAPH_URL:
        logging.error("[WA] ACCESS_TOKEN or GRAPH_URL not configured")
        return 0, {"error": "missing config"}

    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(GRAPH_URL, headers=headers, data=json.dumps(payload), timeout=20)
        try:
            data = resp.json()
        except Exception:
            data = resp.text
        logging.info(f"[WA RESP {resp.status_code}] {data}")
        return resp.status_code, data
    except Exception as e:
        logging.exception("[WA] POST failed")
        return 0, {"error": str(e)}


# ──────────────────────────────────────────────────────────────────────────────
# Simple text message
# ──────────────────────────────────────────────────────────────────────────────
def send_whatsapp_text(to: str, body: str) -> Tuple[int, Any]:
    to_norm = normalize_wa(to)
    if not to_norm:
        logging.warning("[WA TEXT] invalid recipient")
        return 0, {"error": "invalid recipient"}

    payload = {
        "messaging_product": "whatsapp",
        "to": to_norm,
        "type": "text",
        "text": {"body": body},
    }
    return _wa_post(payload)


# ──────────────────────────────────────────────────────────────────────────────
# Template message (approved HSM)
# components example:
#   [{"type":"body","parameters":[{"type":"text","text":"09:00"}]}]
# ──────────────────────────────────────────────────────────────────────────────
def send_whatsapp_template(to: str, template_name: str, components: list[dict] | None = None,
                           lang_code: str = "en") -> Tuple[int, Any]:
    to_norm = normalize_wa(to)
    if not to_norm:
        logging.warning("[WA TPL] invalid recipient")
        return 0, {"error": "invalid recipient"}

    template_obj: Dict[str, Any] = {
        "name": template_name,
        "language": {"code": lang_code},
    }
    if components:
        template_obj["components"] = components

    payload = {
        "messaging_product": "whatsapp",
        "to": to_norm,
        "type": "template",
        "template": template_obj,
    }
    return _wa_post(payload)


# ──────────────────────────────────────────────────────────────────────────────
# Interactive: List picker
# rows: [{"id":"ROW_ID","title":"Title","description":"desc"}, ...]
# WhatsApp caps: <=10 rows total in list UI per message
# ──────────────────────────────────────────────────────────────────────────────
def send_whatsapp_list(to: str, title: str, body: str, menu_id: str, rows: list[dict]) -> Tuple[int, Any]:
    to_norm = normalize_wa(to)
    if not to_norm:
        logging.warning("[WA LIST] invalid recipient")
        return 0, {"error": "invalid recipient"}

    # WhatsApp list structure: 1 section; button label mandatory (<=20 chars)
    button_label = "Choose"
    section = {"title": title[:24] or "Options", "rows": rows[:10]}

    payload = {
        "messaging_product": "whatsapp",
        "to": to_norm,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": title[:60]},
            "body": {"text": body[:1024]},
            "action": {"button": button_label, "sections": [section]},
            # NOTE: menu_id is not a WA field; kept in your row ids, e.g., "ADMIN_PICK_CLIENT_123"
        },
    }
    return _wa_post(payload)


# ──────────────────────────────────────────────────────────────────────────────
# Interactive: Reply buttons (max 3)
# buttons: [{"id":"BTN_ID","title":"Text"}, ...] (max 3)
# ──────────────────────────────────────────────────────────────────────────────
def send_whatsapp_buttons(to: str, body: str, buttons: list[dict], header: str | None = None) -> Tuple[int, Any]:
    to_norm = normalize_wa(to)
    if not to_norm:
        logging.warning("[WA BTNS] invalid recipient")
        return 0, {"error": "invalid recipient"}

    btns = [{
        "type": "reply",
        "reply": {"id": b["id"], "title": b["title"][:20]}
    } for b in buttons[:3]]

    interactive = {
        "type": "button",
        "body": {"text": body[:1024]},
        "action": {"buttons": btns},
    }
    if header:
        interactive["header"] = {"type": "text", "text": header[:60]}

    payload = {
        "messaging_product": "whatsapp",
        "to": to_norm,
        "type": "interactive",
        "interactive": interactive,
    }
    return _wa_post(payload)
