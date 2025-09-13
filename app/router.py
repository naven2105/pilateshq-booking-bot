# router.py
"""
Router
------
Webhook entrypoint for all inbound WhatsApp messages.
- Distinguishes admin vs client.
- Routes notifications vs queries.
- Uses queries.py + formatters.py for ad-hoc inbound requests.
"""

import logging
from flask import Blueprint, request
from . import utils, crud, queries, formatters

router_bp = Blueprint("router", __name__)
log = logging.getLogger(__name__)


# --- Intent Detection (basic, replaceable with NLP later) ---

def detect_intent(body: str, is_admin: bool) -> str:
    text = body.strip().lower()

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
        if "09" in text or "clients booked" in text:
            return "admin_clients_for_time"
        if "how many clients today" in text:
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
    """
    WhatsApp webhook entrypoint.
    """
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

        if reply:
            utils.send_whatsapp_text(from_wa, reply)
            return "ok", 200
        else:
            utils.send_whatsapp_text(from_wa, "❓ Sorry, I didn’t understand that. Please try again.")
            return "unknown", 200

    except Exception:
        log.exception("webhook failed")
        return "error", 500


# --- Intent Handlers ---

def handle_intent(intent: str, from_wa: str, body: str, is_admin: bool) -> str:
    """Map intent → queries.py → formatters.py → response string"""

    # --- Client Intents ---
    if intent == "client_next_lesson":
        result = queries.get_next_lesson(crud.get_client_id(from_wa))
        return formatters.format_next_lesson(result)

    if intent == "client_sessions_week":
        result = queries.get_sessions_this_week(crud.get_client_id(from_wa))
        return formatters.format_sessions_this_week(result)

    if intent == "client_cancel_next":
        success = queries.cancel_next_lesson(crud.get_client_id(from_wa))
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
        # Example assumes "09h00" is always mentioned
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
