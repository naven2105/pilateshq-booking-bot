"""
client_menu_router.py – Phase 26 (Client Self-Service Menu + Admin Template)
────────────────────────────────────────────────────────────
Purpose:
 • Send the PilatesHQ client self-service menu (template)
 • Handle button payloads from Meta interactive replies
 • Route actions to bookings / attendance / reschedule modules
 • Send all admin communications via WhatsApp template (admin_generic_alert_us)
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

# ─────────────────────────────────────────────────────────────
bp = Blueprint("client_menu", __name__)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Environment variables
# ─────────────────────────────────────────────────────────────
NADINE_WA = os.getenv("NADINE_WA", "")
TEMPLATE_LANG = os.getenv("TEMPLATE_LANG", "en_US")

# Approved WhatsApp Templates
MENU_TEMPLATE = "pilateshq_menu_main"
ADMIN_TEMPLATE = "admin_generic_alert_us"

# ─────────────────────────────────────────────────────────────
# Helper: Send main client menu
# ─────────────────────────────────────────────────────────────
def send_client_menu(wa_number: str, name: str = "there"):
    """Send the PilatesHQ client self-service menu via WhatsApp template."""
    try:
        log.info(f"[client_menu] Sending main menu to {wa_number}")
        return send_whatsapp_template(wa_number, MENU_TEMPLATE, TEMPLATE_LANG, [name])
    except Exception as e:
        log.error(f"❌ Failed to send client menu: {e}")
        return {"ok": False, "error": str(e)}

# ─────────────────────────────────────────────────────────────
# Helper: Send admin menu using approved template
# ─────────────────────────────────────────────────────────────
def send_admin_menu(wa_number: str):
    """Send a simplified admin command reference via Meta-approved template."""
    try:
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
        send_whatsapp_template(
            wa_number,
            ADMIN_TEMPLATE,
            TEMPLATE_LANG,
            [help_text]
        )
        log.info(f"✅ Admin menu sent via template to {wa_number}")
    except Exception as e:
        log.error(f"⚠️ send_admin_menu failed: {e}")
        # fallback in case of template failure (only within 24h session)
        try:
            send_whatsapp_text(wa_number, help_text)
        except Exception as inner:
            log.error(f"❌ Admin menu text fallback failed: {inner}")

# ─────────────────────────────────────────────────────────────
# API Route: Trigger menu manually (for testing)
# ─────────────────────────────────────────────────────────────
@bp.route("/client-menu/send", methods=["POST"])
def send_menu_api():
    """Trigger menu manually (e.g., via Postman or PowerShell)."""
    try:
        payload = request.get_json(force=True) or {}
        wa_number = normalize_wa(payload.get("wa_number", ""))
        name = payload.get("name", "there")
        res = send_client_menu(wa_number, name)
        return jsonify(res), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ─────────────────────────────────────────────────────────────
# API Route: Handle interactive button payloads
# ─────────────────────────────────────────────────────────────
@bp.route("/client-menu/action", methods=["POST"])
def handle_client_action():
    """
    Receive interactive button payloads from WhatsApp.
    Example:
    {
        "wa_number": "2784313635",
        "payload": "MY_SCHEDULE",
        "name": "Mary Smith"
    }
    """
    try:
        payload = request.get_json(force=True) or {}
        wa_number = normalize_wa(payload.get("wa_number", ""))
        name = payload.get("name", "there")
        action = (payload.get("payload") or "").upper().strip()

        log.info(f"[client_menu] Action received: {action} from {wa_number}")

        # ─────────────── Route by payload ───────────────
        if action == "MY_SCHEDULE":
            client_bookings.show_bookings(wa_number)
            return jsonify({"ok": True, "routed": "bookings"}), 200

        if action == "BOOK_SESSION":
            send_safe_message(
                NADINE_WA,
                f"📩 Client *{name}* ({wa_number}) would like to *book a session*.",
                label="menu_book_session",
            )
            send_safe_message(
                wa_number,
                "✅ Nadine has been notified to confirm your booking.",
                label="menu_book_session_client",
            )
            return jsonify({"ok": True, "routed": "booking_request"}), 200

        if action == "RESCHEDULE":
            handle_reschedule_event(name, wa_number, "reschedule")
            return jsonify({"ok": True, "routed": "reschedule"}), 200

        if action == "CANCEL_NEXT":
            client_bookings.cancel_next(wa_number)
            return jsonify({"ok": True, "routed": "cancel_next"}), 200

        if action == "RUNNING_LATE":
            client_attendance.running_late(wa_number)
            return jsonify({"ok": True, "routed": "running_late"}), 200

        if action == "SICK_TODAY":
            client_attendance.mark_sick_today(wa_number)
            return jsonify({"ok": True, "routed": "sick_today"}), 200

        if action == "CONTACT_NADINE":
            send_safe_message(
                NADINE_WA,
                f"📞 Client *{name}* ({wa_number}) requested to be contacted.",
                label="menu_contact_admin",
            )
            send_safe_message(
                wa_number,
                "💬 Nadine will get back to you shortly. 💜",
                label="menu_contact_ack",
            )
            return jsonify({"ok": True, "routed": "contact_admin"}), 200

        # ─────────────── Unknown payload fallback ───────────────
        log.warning(f"⚠️ Unknown menu payload: {action}")
        send_safe_message(
            wa_number,
            "⚠ Sorry, I didn’t recognise that menu option. Please try again or type *menu*.",
            label="menu_unknown",
        )
        return jsonify({"ok": False, "error": "unknown payload"}), 400

    except Exception as e:
        log.error(f"❌ Error in handle_client_action: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

# ─────────────────────────────────────────────────────────────
# Health check route
# ─────────────────────────────────────────────────────────────
@bp.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "client_menu_router"}), 200
