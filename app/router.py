# app/router.py
"""
Router
------
Webhook entrypoint for all inbound WhatsApp messages.
- Distinguishes admin vs client.
- Routes notifications vs queries.
- Uses queries.py + formatters.py for ad-hoc inbound requests.
"""

import logging
from datetime import date
from typing import Any, Dict, Optional
from flask import Blueprint, request

# Explicit imports from app
from . import utils, crud, formatters
import app.queries as queries  # explicitly import the module file, not package __init__

router_bp = Blueprint("router", __name__)
log = logging.getLogger(__name__)


# --- Intent Detection (basic, replaceable with NLP later) ---

GREET_WORDS = ("hi", "hello", "hey", "menu", "help", "start", "yo", "howzit", "morning", "afternoon", "evening")

def detect_intent(body: str, is_admin: bool) -> str:
    text = (body or "").strip().lower()

    # Greeting / menu
    if any(w in text for w in GREET_WORDS):
        return "greet"

    # Client queries
    if not is_admin:
        if "next lesson" in text:
            return "client_next_lesson"
        if "this week" in text:
            return "client_sessions_week"
        if "cancel" in text:
            return "client_cancel_next"
        if "weekly schedule" in text:
            return "client_weekly_schedule"

    # Admin queries
    if is_admin:
        if "sessions for" in text:
            return "admin_client_sessions"
        if "clients booked" in text or "09" in text:
            return "admin_clients_for_time"
        if "how many clients today" in text or "clients today" in text:
            return "admin_clients_today"
        if "cancellations" in text:
            return "admin_cancellations"

    # General info (anyone)
    if "date" in text:
        return "info_date"
    if "time" in text:
        return "info_time"
    if "address" in text:
        return "info_address"
    if "rules" in text:
        return "info_rules"

    return "unknown"


# --- Webhook ---

@router_bp.post("/webhook")
def webhook():
    """WhatsApp webhook entrypoint."""
    try:
        data = request.json
        log.info(f"[router] inbound: {data}")

        msg = utils.extract_message(data)
        if not msg:
            return "no message", 200

        from_wa = msg["from"]
        body = msg["body"]

        # Determine role
        is_admin = utils.is_admin(from_wa)

        # Detect intent
        intent = detect_intent(body, is_admin)
        log.info(f"[router] from={from_wa} admin={is_admin} intent={intent}")

        reply = handle_intent(intent, from_wa, body, is_admin)

        # Reply can be a string (text) or a dict(kind='buttons', text, buttons)
        if isinstance(reply, dict) and reply.get("kind") == "buttons":
            utils.send_whatsapp_buttons(from_wa, reply["text"], reply["buttons"])
            return "ok", 200
        elif isinstance(reply, str) and reply:
            utils.send_whatsapp_text(from_wa, reply)
            return "ok", 200
        else:
            # Fallback to menu if nothing returned
            menu = default_menu_payload(is_admin)
            utils.send_whatsapp_buttons(from_wa, menu["text"], menu["buttons"])
            return "ok", 200

    except Exception:
        log.exception("webhook failed")
        return "error", 500


# --- Intent Handlers ---

def handle_intent(intent: str, from_wa: str, body: str, is_admin: bool) -> Optional[Any]:
    """Map intent → queries.py → formatters.py → response payload"""

    # --- Greeting / Menu (works for both roles) ---
    if intent in ("greet", "unknown"):
        return default_menu_payload(is_admin)

    # --- Client Intents ---
    if intent == "client_next_lesson":
        cid = crud.get_client_id(from_wa)
        result = queries.get_next_lesson(cid) if cid else None
        return formatters.format_next_lesson(result)

    if intent == "client_sessions_week":
        cid = crud.get_client_id(from_wa)
        result = queries.get_sessions_this_week(cid) if cid else []
        return formatters.format_sessions_this_week(result)

    if intent == "client_cancel_next":
        cid = crud.get_client_id(from_wa)
        success = queries.cancel_next_lesson(cid) if cid else False
        return "✅ Your next lesson was cancelled." if success else "⚠ No upcoming lesson to cancel."

    if intent == "client_weekly_schedule":
        result = queries.get_weekly_schedule()
        return formatters.format_weekly_schedule(result)

    # --- Admin Intents ---
    if intent == "admin_client_sessions":
        # Extract client name from message body
        client_name = body.replace("sessions for", "").strip()
        result = queries.get_client_sessions(client_name)
        return formatters.format_client_sessions(result, client_name)

    if intent == "admin_clients_for_time":
        # Example assumes "09h00" is always mentioned (can be extended)
        result = queries.get_clients_for_time(str(date.today()), "09:00")
        return formatters.format_clients_for_time(result, "09:00", str(date.today()))

    if intent == "admin_clients_today":
        result = queries.get_clients_today()
        return formatters.format_clients_today(result)

    if intent == "admin_cancellations":
        result = queries.get_cancellations_today()
        return formatters.format_cancellations(result)

    # --- Info Intents (anyone) ---
    if intent == "info_date":
        return formatters.format_today_date(queries.get_today_date())

    if intent == "info_time":
        return formatters.format_current_time(queries.get_current_time())

    if intent == "info_address":
        return formatters.format_studio_address(queries.get_studio_address())

    if intent == "info_rules":
        return formatters.format_studio_rules(queries.get_studio_rules())

    return None


# --- Menu builder (buttons) ---

def default_menu_payload(is_admin: bool) -> Dict[str, Any]:
    """
    Build a 3-button quick menu depending on role.
    """
    if is_admin:
        text = (
            "👋 *PilatesHQ Admin*\n"
            "Choose an option:"
        )
        buttons = [
            {"id": "ADMIN_CLIENTS_TODAY", "title": "Clients today"},
            {"id": "ADMIN_09H", "title": "Who @09:00?"},
            {"id": "ADMIN_CANCELS", "title": "Cancellations"},
        ]
    else:
        text = (
            "👋 *Welcome to PilatesHQ!*\n"
            "How can I help today?"
        )
        buttons = [
            {"id": "CLIENT_NEXT", "title": "Next lesson"},
            {"id": "CLIENT_WEEK", "title": "This week"},
            {"id": "CLIENT_CANCEL", "title": "Cancel next"},
        ]
    return {"kind": "buttons", "text": text, "buttons": buttons}
