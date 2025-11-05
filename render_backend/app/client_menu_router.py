"""
client_menu_router.py – Phase 27E (Unified REQUEST_TIMEOUT Config)
────────────────────────────────────────────────────────────
Enhancement:
 • Centralises all network request timeouts under REQUEST_TIMEOUT
 • Default = 35 seconds, override via environment variable
 • Fully consistent with router_webhook.py
 • Still sends weekly summary using WhatsApp template client_generic_alert_us
────────────────────────────────────────────────────────────
"""

import os
import logging
import requests
from flask import Blueprint, request, jsonify
from .utils import (
    send_whatsapp_template,
    send_safe_message,
    send_whatsapp_text,
    normalize_wa
)

bp = Blueprint("client_menu", __name__)
log = logging.getLogger(__name__)

# ── Environment ─────────────────────────────────────────────
NADINE_WA = os.getenv("NADINE_WA", "")
TEMPLATE_LANG = os.getenv("TEMPLATE_LANG", "en_US")
MENU_TEMPLATE = "pilateshq_menu_main"
CLIENT_ALERT_TEMPLATE = "client_generic_alert_us"
ADMIN_TEMPLATE = "admin_generic_alert_us"
GAS_WEBHOOK_URL = os.getenv("GAS_WEBHOOK_URL", "")
WEBHOOK_BASE = os.getenv("WEBHOOK_BASE", "https://pilateshq-booking-bot.onrender.com")

# Global timeout (default 35s, override via environment)
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "35"))

# GAS & local endpoints
INVOICE_ENDPOINT = f"{WEBHOOK_BASE}/invoices/review-one"

# ─────────────────────────────────────────────────────────────
# Menu sender
# ─────────────────────────────────────────────────────────────
def send_client_menu(wa_number: str, name: str = "there"):
    """Send the PilatesHQ client menu (template-based)."""
    try:
        send_whatsapp_template(wa_number, MENU_TEMPLATE, TEMPLATE_LANG, [name])
        log.info(f"✅ Menu template sent to {wa_number}")
        return {"ok": True}
    except Exception as e:
        log.error(f"❌ send_client_menu failed: {e}")
        send_whatsapp_text(wa_number, "⚠️ Sorry, menu unavailable right now.")
        return {"ok": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────
# Button payload handler (7-day schedule)
# ─────────────────────────────────────────────────────────────
@bp.route("/action", methods=["POST"])
def handle_client_action():
    """Handles quick-reply button responses from client menu."""
    data = request.get_json(force=True) or {}
    wa_number = normalize_wa(data.get("wa_number", ""))
    name = data.get("name", "there")
    action = (data.get("payload") or "").strip().lower()

    log.info(f"[client_menu] Action received: {action} from {wa_number}")

    try:
        # 1️⃣ My Schedule – sends 7-day summary via template
        if "schedule" in action:
            if GAS_WEBHOOK_URL:
                r = requests.post(
                    GAS_WEBHOOK_URL,
                    json={"action": "export_sessions_week", "wa_number": wa_number},
                    timeout=REQUEST_TIMEOUT
                )
                if r.ok:
                    result = r.json()
                    summary = result.get("summary", "")
                    if summary:
                        send_whatsapp_template(
                            wa_number,
                            CLIENT_ALERT_TEMPLATE,
                            TEMPLATE_LANG,
                            [summary]
                        )
                        log.info(f"📆 Sent 7-day schedule template to {wa_number}")
                        return jsonify({"ok": True, "summary": summary}), 200
                    else:
                        send_whatsapp_text(
                            wa_number, "📭 No booked sessions found in the next 7 days."
                        )
                        return jsonify({"ok": True, "summary": "none"}), 200
            send_whatsapp_text(wa_number, "⚠️ Unable to fetch your schedule right now.")
            return jsonify({"ok": False}), 200

        # 2️⃣ Check Availability
        if "availability" in action:
            if GAS_WEBHOOK_URL:
                r = requests.post(
                    GAS_WEBHOOK_URL,
                    json={"action": "get_group_availability"},
                    timeout=REQUEST_TIMEOUT
                )
                if r.ok:
                    send_safe_message(
                        wa_number,
                        "✅ Nadine will confirm your slot shortly. Thank you for checking availability!"
                    )
                    send_safe_message(
                        NADINE_WA, f"📩 Client *{name}* ({wa_number}) checked availability."
                    )
                    return jsonify({"ok": True, "routed": "availability"}), 200
            send_whatsapp_text(wa_number, "⚠️ Unable to check availability right now.")
            return jsonify({"ok": False}), 200

        # 3️⃣ View Latest Invoice
        if "invoice" in action:
            try:
                r = requests.post(
                    INVOICE_ENDPOINT,
                    json={"client_name": name},
                    timeout=REQUEST_TIMEOUT
                )
                if r.ok:
                    send_safe_message(
                        wa_number,
                        "🧾 Your latest invoice has been sent via WhatsApp and email."
                    )
                    return jsonify({"ok": True, "routed": "invoice"}), 200
            except Exception as e:
                log.warning(f"Invoice error: {e}")
            send_whatsapp_text(wa_number, "⚠️ Unable to retrieve your invoice right now.")
            return jsonify({"ok": False}), 200

        # Unrecognised payload
        send_whatsapp_text(
            wa_number,
            "❓Sorry, I didn’t understand that option. Please type *menu* to try again."
        )
        return jsonify({"ok": False, "error": "unknown payload"}), 400

    except Exception as e:
        log.error(f"⚠️ handle_client_action failed: {e}")
        send_whatsapp_text(wa_number, "⚠️ Something went wrong. Please try again later.")
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# API trigger – manual send
# ─────────────────────────────────────────────────────────────
@bp.route("/send", methods=["POST"])
def send_menu_api():
    data = request.get_json(force=True) or {}
    wa_number = normalize_wa(data.get("wa_number", ""))
    name = data.get("name", "there")
    return jsonify(send_client_menu(wa_number, name)), 200


# ─────────────────────────────────────────────────────────────
# Health check
# ─────────────────────────────────────────────────────────────
@bp.route("/health", methods=["GET"])
@bp.route("", methods=["GET"])
@bp.route("/", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "client_menu_router",
        "timeout": REQUEST_TIMEOUT
    }), 200
