# app/utils.py
import logging
import requests
from typing import Iterable, Optional, Union, Dict, Any, List

from .config import ACCESS_TOKEN, GRAPH_URL

# ──────────────────────────────────────────────────────────────────────────────
# Phone helpers
# ──────────────────────────────────────────────────────────────────────────────
def normalize_wa(raw: str) -> str:
    """
    Normalize SA phone numbers to +27… format.
    Accepts 0…, 27…, +27… and returns +27…
    """
    if not raw:
        return ""
    n = str(raw).strip().replace(" ", "").replace("-", "")
    if n.startswith("+27"):
        return n
    if n.startswith("27"):
        return "+" + n
    if n.startswith("0"):
        return "+27" + n[1:]
    return n


# ──────────────────────────────────────────────────────────────────────────────
# Low-level sender
# ──────────────────────────────────────────────────────────────────────────────
def _send_json(payload: dict) -> Optional[dict]:
    """
    Sends a raw payload to the WhatsApp Cloud API.
    Returns parsed JSON on success, or None on error. Logs response either way.
    """
    try:
        headers = {
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "Content-Type": "application/json",
        }
        resp = requests.post(GRAPH_URL, headers=headers, json=payload, timeout=15)
        logging.info(f"[WA RESP {resp.status_code}] {resp.text}")
        try:
            return resp.json()
        except Exception:
            return None
    except Exception as e:
        logging.exception(f"[WA SEND ERROR] {e}")
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Text & interactive helpers (unchanged, still useful in-session)
# ──────────────────────────────────────────────────────────────────────────────
def send_whatsapp_text(to: str, body: str):
    _send_json({
        "messaging_product": "whatsapp",
        "to": normalize_wa(to),
        "type": "text",
        "text": {"body": body[:4096]},
    })


def send_whatsapp_list(to: str, header: str, body: str, button_id: str, options: list):
    """
    options: list of {"id": "...", "title": "...", "description": "...?"}
    Max 10 rows; title <= 24 chars; description <= 72 chars.
    """
    rows = []
    for opt in options[:10]:
        rows.append({
            "id": opt["id"],
            "title": opt["title"][:24],
            "description": (opt.get("description", "") or "")[:72],
        })
    payload = {
        "messaging_product": "whatsapp",
        "to": normalize_wa(to),
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": header[:60]},
            "body": {"text": body[:1024]},
            "action": {
                "button": "Choose",
                "sections": [{"title": "Options", "rows": rows}],
            },
        },
    }
    _send_json(payload)


def send_whatsapp_buttons(to: str, body: str, buttons: list):
    """
    buttons: list of {"id": "...", "title": "..."}
    Max 3 buttons; title <= 20 chars.
    """
    btns = []
    for b in buttons[:3]:
        btns.append({
            "type": "reply",
            "reply": {"id": b["id"], "title": b["title"][:20]},
        })
    payload = {
        "messaging_product": "whatsapp",
        "to": normalize_wa(to),
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body[:1024]},
            "action": {"buttons": btns},
        },
    }
    _send_json(payload)


# ──────────────────────────────────────────────────────────────────────────────
# Template sender (NEW)
# ──────────────────────────────────────────────────────────────────────────────
def _as_str_list(values: Optional[Iterable[Any]]) -> List[str]:
    if not values:
        return []
    return ["" if v is None else str(v) for v in values]


def send_template_message(
    to: str,
    template_name: str,
    body_params: Optional[Iterable[Any]] = None,
    *,
    header_params: Optional[Iterable[Any]] = None,
    button_params: Optional[Iterable[Iterable[Any]]] = None,
    language_code: str = "en_ZA",
) -> Optional[dict]:
    """
    Send a WhatsApp *template* message (HSM).

    Args:
        to: phone number (any SA variant; normalized internally).
        template_name: the approved template name in Meta (e.g. 'session_next_hour').
        body_params: positional variables for the BODY {{1}}, {{2}}, …
        header_params: positional variables for the HEADER (if your template uses a text header).
        button_params: list-of-lists for QUICK_REPLY/URL button params (rarely needed).
        language_code: ISO code of the approved template language (e.g. 'en_ZA').

    Returns:
        Parsed response JSON or None.

    Notes:
        • Meta requires positional placeholders ({{1}}, {{2}}). Pass them in order.
        • Keep the number of params exactly matching what the template expects.
    """
    components: List[Dict[str, Any]] = []

    # Header
    if header_params:
        components.append({
            "type": "header",
            "parameters": [{"type": "text", "text": p} for p in _as_str_list(header_params)],
        })

    # Body
    if body_params:
        components.append({
            "type": "body",
            "parameters": [{"type": "text", "text": p} for p in _as_str_list(body_params)],
        })

    # Buttons (optional, typically empty for our current templates)
    if button_params:
        btns: List[Dict[str, Any]] = []
        # Each inner list is parameters for a single button (positional)
        for group in button_params:
            btns.append({
                "type": "button",
                "sub_type": "quick_reply",  # or "url" if your template defines URL buttons
                "index": str(len(btns)),    # 0-based
                "parameters": [{"type": "text", "text": p} for p in _as_str_list(group)],
            })
        if btns:
            components.extend(btns)

    payload = {
        "messaging_product": "whatsapp",
        "to": normalize_wa(to),
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language_code},
            "components": components or [],
        },
    }
    return _send_json(payload)


# ──────────────────────────────────────────────────────────────────────────────
# Convenience wrappers for your approved templates (optional but handy)
# Adjust the number/meaning of params to match the exact approved body text.
# ──────────────────────────────────────────────────────────────────────────────

def tpl_session_next_hour(to: str, start_time: str):
    """
    Template: session_next_hour (client)
    Body: "⏰ Reminder: Your Pilates session starts at {{1}} today. Reply CANCEL if you cannot attend."
    """
    return send_template_message(to, "session_next_hour", [start_time])

def tpl_session_tomorrow(to: str, start_time: str):
    """
    Template: session_tomorrow (client)
    Body: "📅 Reminder: Your Pilates session is tomorrow at {{1}}."
    """
    return send_template_message(to, "session_tomorrow", [start_time])

def tpl_admin_hourly_update(to: str, next_hour_time: str, status_line: str):
    """
    Template: admin_hourly_update (admin)
    Example Body: "Next hour session: {{1}}. Status: {{2}}."
    """
    return send_template_message(to, "admin_hourly_update", [next_hour_time, status_line])

def tpl_admin_20h00(to: str, upcoming_count: Union[int, str], details_flat: str):
    """
    Template: admin_20h00 (admin daily recap)
    Example Body (safe): "Upcoming sessions: {{1}}. Details: {{2}}"
    • Keep {{2}} length small enough to pass policy—truncate to ~900 chars in caller if needed.
    """
    return send_template_message(to, "admin_20h00", [str(upcoming_count), details_flat])

def tpl_admin_cancel_all_sessions(to: str, day_label: str):
    """
    Template: admin_cancel_all_sessions_admin_sick_unavailable (admin broadcast)
    Example Body: "All sessions on {{1}} are cancelled. We’ll follow up with new dates."
    """
    return send_template_message(to, "admin_cancel_all_sessions_admin_sick_unavailable", [day_label])

def tpl_admin_update(to: str, field_label: str, current_value: str):
    """
    Template: admin_update (admin form-ish prompt)
    Example Body: "Update {{1}}. Current: {{2}}."
    """
    return send_template_message(to, "admin_update", [field_label, current_value])
