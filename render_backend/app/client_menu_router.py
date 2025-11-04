"""
client_menu_router.py – Phase 26B (Client Self-Service + Admin Template + Health)
────────────────────────────────────────────────────────────
"""

import os
import logging
from flask import Blueprint, request, jsonify
from .utils import (
    send_whatsapp_template,
    send_safe_message,
    send_whatsapp_text,
    normalize_wa
)
from . import client_bookings, client_attendance
from .client_reschedule_handler import handle_reschedule_event

bp = Blueprint("client_menu", __name__)
log = logging.getLogger(__name__)

NADINE_WA = os.getenv("NADINE_WA", "")
TEMPLATE_LANG = os.getenv("TEMPLATE_LANG", "en_US")
MENU_TEMPLATE = "pilateshq_menu_main"
ADMIN_TEMPLATE = "admin_generic_alert_us"

def send_client_menu(wa_number: str, name: str = "there"):
    """Send the PilatesHQ client menu."""
    try:
        return send_whatsapp_template(wa_number, MENU_TEMPLATE, TEMPLATE_LANG, [name])
    except Exception as e:
        log.error(f"❌ send_client_menu failed: {e}")
        return {"ok": False, "error": str(e)}

def send_admin_menu(wa_number: str):
    """Send admin command list via approved template."""
    help_text = (
        "🛠️ PilatesHQ Admin Commands:\n"
        "• book [client] – Add standing slot\n"
        "• suspend [client] – Suspend slot\n"
        "• resume [client] – Resume slot\n"
        "• deactivate [client] – Deactivate client\n"
        "• export clients / today / week – Export PDF\n"
        "• invoice [client] – Generate invoice\n"
        "• unpaid invoices – List overdue\n"
        "• birthdays – Weekly digest\n\n"
        "💡 Tip: Send 'menu' to view this list again."
    )
    try:
        send_whatsapp_template(wa_number, ADMIN_TEMPLATE, TEMPLATE_LANG, [help_text])
    except Exception as e:
        log.warning(f"⚠️ Template failed, falling back to text: {e}")
        send_whatsapp_text(wa_number, help_text)

@bp.route("/send", methods=["POST"])
def send_menu_api():
    """Trigger menu manually."""
    data = request.get_json(force=True) or {}
    wa_number = normalize_wa(data.get("wa_number", ""))
    name = data.get("name", "there")
    return jsonify(send_client_menu(wa_number, name)), 200

@bp.route("/action", methods=["POST"])
def handle_client_action():
    """Button payload handler."""
    data = request.get_json(force=True) or {}
    wa_number = normalize_wa(data.get("wa_number", ""))
    name = data.get("name", "there")
    action = (data.get("payload") or "").upper().strip()
    log.info(f"[client_menu] Action received: {action} from {wa_number}")

    if action == "MY_SCHEDULE":
        client_bookings.show_bookings(wa_number)
        return jsonify({"ok": True, "routed": "bookings"}), 200
    if action == "BOOK_SESSION":
        send_safe_message(NADINE_WA, f"📩 Client *{name}* ({wa_number}) wants to book.")
        send_safe_message(wa_number, "✅ Nadine has been notified to confirm your booking.")
        return jsonify({"ok": True, "routed": "booking_request"}), 200

    return jsonify({"ok": False, "error": "unknown payload"}), 400

# ─────────────────────────────────────────────────────────────
# Health check routes (fix redirect)
# ─────────────────────────────────────────────────────────────
@bp.route("/health", methods=["GET"])
@bp.route("", methods=["GET"])
@bp.route("/", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "client_menu_router"
    }), 200
