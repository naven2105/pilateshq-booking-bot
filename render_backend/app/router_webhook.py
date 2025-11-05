"""
router_webhook.py – Phase 26E (Unified Timeout + Interactive Buttons + Lean Logging)
────────────────────────────────────────────────────────────
Handles all incoming Meta Webhook events (GET verify + POST messages).

✅ Includes:
 • Extracts contact name from ‘contacts’
 • Detects interactive replies (buttons / lists / legacy button type) → forwards to /client-menu/action
 • Centralised timeout constant for all network requests (REQUEST_TIMEOUT = 20)
 • Admin commands:
      – book / suspend / resume / deactivate
      – invoice {client}
      – unpaid invoices / credits
      – export clients / today / week
      – birthdays digest
 • 🔁 Client & Admin reschedule handling
 • 🧭 Client Self-Service Menu trigger (“menu”, “help”)
 • Context-aware fallback:
      – Admin → WhatsApp template (admin_generic_alert_us)
      – Client → shows menu
      – Guest → Meta template (guest_welcome_us) or fallback text
────────────────────────────────────────────────────────────
"""

import os
import json
import requests
from flask import Blueprint, request, jsonify
from .utils import send_whatsapp_text, send_whatsapp_template
from .client_reschedule_handler import handle_reschedule_event
from .client_menu_router import send_client_menu

# ─────────────────────────────────────────────────────────────
router_bp = Blueprint("router_bp", __name__)

# ── Environment variables ─────────────────────────────────────
VERIFY_TOKEN           = os.getenv("META_VERIFY_TOKEN", "")
WEBHOOK_BASE           = os.getenv("WEBHOOK_BASE", "https://pilateshq-booking-bot.onrender.com")
NADINE_WA              = os.getenv("NADINE_WA", "")
TEMPLATE_LANG          = os.getenv("TEMPLATE_LANG", "en_US")
TEMPLATE_GUEST_WELCOME = os.getenv("TEMPLATE_GUEST_WELCOME", "guest_welcome_us")
GAS_WEBHOOK_URL        = os.getenv("GAS_WEBHOOK_URL", "")
DEBUG_MODE             = os.getenv("DEBUG_MODE", "false").lower() == "true"

# ── Endpoint constants ────────────────────────────────────────
STANDING_ENDPOINT = f"{WEBHOOK_BASE}/tasks/standing/command"
INVOICE_ENDPOINT  = f"{WEBHOOK_BASE}/invoices/review-one"
UNPAID_ENDPOINT   = f"{WEBHOOK_BASE}/invoices/unpaid"
CLIENT_MENU_ACTION_ENDPOINT = f"{WEBHOOK_BASE}/client-menu/action"

# ── Global timeout constant ───────────────────────────────────
REQUEST_TIMEOUT = 20   # seconds


# ─────────────────────────────────────────────────────────────
# Helper: Admin template notification
# ─────────────────────────────────────────────────────────────
def notify_admin(message: str):
    """Send a Meta-approved template alert to Nadine."""
    try:
        send_whatsapp_template(
            NADINE_WA,
            "admin_generic_alert_us",
            TEMPLATE_LANG,
            [message]
        )
        print(f"✅ Admin alert: {message}")
    except Exception as e:
        print(f"⚠️ notify_admin failed: {e}")


# ─────────────────────────────────────────────────────────────
# Helper: Extract message text or interactive payload
# ─────────────────────────────────────────────────────────────
def extract_message_text(msg: dict) -> str:
    """
    Normalize WhatsApp message content to a command-ish string.

    Supports:
      • text → returns body
      • interactive.button_reply / list_reply → returns id/title
      • legacy type=button → returns payload/text
    Always returns uppercase.
    """
    mtype = (msg.get("type") or "").lower()

    # plain text
    if mtype == "text":
        body = (msg.get("text") or {}).get("body", "")
        return body.strip().upper()

    # modern interactive
    if mtype == "interactive":
        i = msg.get("interactive") or {}
        if i.get("button_reply"):
            b = i["button_reply"]
            return (b.get("id") or b.get("title") or "").strip().upper()
        if i.get("list_reply"):
            l = i["list_reply"]
            return (l.get("id") or l.get("title") or "").strip().upper()

    # legacy button type (as seen in recent Meta payloads)
    if mtype == "button":
        b = msg.get("button") or {}
        return (b.get("payload") or b.get("text") or "").strip().upper()

    return ""


# ─────────────────────────────────────────────────────────────
# Helper: Forward client action to /client-menu/action
# ─────────────────────────────────────────────────────────────
def forward_client_action(payload: str, wa_number: str, name: str):
    try:
        requests.post(
            CLIENT_MENU_ACTION_ENDPOINT,
            json={"wa_number": wa_number, "name": name, "payload": payload},
            timeout=REQUEST_TIMEOUT
        )
        print(f"➡️ Forwarded action '{payload}' to client_menu_router for {wa_number}")
    except Exception as e:
        print(f"⚠️ Failed to forward client action '{payload}': {e}")


# ─────────────────────────────────────────────────────────────
# META VERIFICATION HANDSHAKE
# ─────────────────────────────────────────────────────────────
@router_bp.route("/webhook", methods=["GET"])
def verify():
    if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.verify_token") == VERIFY_TOKEN:
        print("✅ Meta webhook verified.")
        return request.args.get("hub.challenge"), 200
    return "Forbidden", 403


# ─────────────────────────────────────────────────────────────
# META MESSAGE HANDLER
# ─────────────────────────────────────────────────────────────
@router_bp.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    if DEBUG_MODE:
        print("📩 Full webhook (DEBUG):", json.dumps(data, indent=2))

    try:
        entry = (data.get("entry") or [{}])[0]
        change = (entry.get("changes") or [{}])[0]
        value = change.get("value", {})

        # statuses
        if "statuses" in value:
            return jsonify({"ok": True, "type": "status"}), 200

        # no messages
        if "messages" not in value:
            return jsonify({"ok": True, "type": "ignored"}), 200

        msg = value["messages"][0]
        wa_number = msg.get("from", "")
        contacts = value.get("contacts", [])
        profile_name = contacts[0]["profile"]["name"] if contacts else "Unknown"
        cmd = extract_message_text(msg)
        lower_text = cmd.lower()

        # ─────────────────────────────
        # ADMIN COMMANDS
        # ─────────────────────────────
        if wa_number == NADINE_WA:
            if any(lower_text.startswith(c) for c in ["book ", "suspend ", "resume "]):
                r = requests.post(STANDING_ENDPOINT, json={"from": wa_number, "text": cmd}, timeout=REQUEST_TIMEOUT)
                notify_admin(f"Standing command processed ({r.status_code})")
                return jsonify({"status": "standing handled"}), 200

            if lower_text.startswith("invoice "):
                client = cmd.split(" ", 1)[1].strip()
                requests.post(INVOICE_ENDPOINT, json={"client_name": client}, timeout=REQUEST_TIMEOUT)
                notify_admin(f"Invoice sent for {client}")
                return jsonify({"status": "invoice handled"}), 200

            if lower_text in ["unpaid invoices", "check invoices"]:
                requests.post(UNPAID_ENDPOINT, json={"action": "list_overdue_invoices"}, timeout=REQUEST_TIMEOUT)
                notify_admin("Unpaid invoices summary requested")
                return jsonify({"status": "unpaid handled"}), 200

            if lower_text.startswith("export"):
                if not GAS_WEBHOOK_URL:
                    notify_admin("GAS webhook not configured.")
                    return jsonify({"status": "missing GAS"}), 200
                mapping = {
                    "clients": ("export_clients", "Clients Register"),
                    "today": ("export_sessions_today", "Today's Sessions"),
                    "week": ("export_sessions_week", "Weekly Sessions")
                }
                match = next(((a, l) for k, (a, l) in mapping.items() if k in lower_text), None)
                if not match:
                    notify_admin("Unknown export command.")
                    return jsonify({"status": "unknown export"}), 200
                action, label = match
                r = requests.post(GAS_WEBHOOK_URL, json={"action": action}, timeout=REQUEST_TIMEOUT)
                notify_admin(f"{label} export {'completed' if r.ok else 'failed'}.")
                return jsonify({"status": "export handled"}), 200

            if lower_text.startswith("deactivate "):
                client = cmd.split(" ", 1)[1].strip()
                r = requests.post(GAS_WEBHOOK_URL, json={"action": "deactivate_client", "client_name": client}, timeout=REQUEST_TIMEOUT)
                notify_admin(f"Deactivated {client}" if r.ok else f"Could not deactivate {client}")
                return jsonify({"status": "deactivate handled"}), 200

            if lower_text in ["birthdays", "birthdays test"]:
                r = requests.post(GAS_WEBHOOK_URL, json={"action": "weekly_birthdays_digest"}, timeout=REQUEST_TIMEOUT)
                notify_admin("🎂 Birthdays digest completed." if r.ok else "Birthdays digest failed.")
                return jsonify({"status": "birthdays handled"}), 200

            send_whatsapp_template(wa_number, "admin_generic_alert_us", TEMPLATE_LANG, [f"You sent '{cmd}'."])
            return jsonify({"status": "admin fallback"}), 200

        # ─────────────────────────────
        # CLIENT MENU / ACTIONS
        # ─────────────────────────────
        if lower_text in ["menu", "help", "hi", "hello", "start"]:
            send_client_menu(wa_number, profile_name)
            return jsonify({"status": "menu sent"}), 200

        if cmd in ("MY_SCHEDULE", "CHECK_AVAILABILITY", "VIEW_INVOICE", "MY SCHEDULE"):
            forward_client_action(cmd, wa_number, profile_name)
            return jsonify({"status": "client action forwarded", "payload": cmd}), 200

        if any(x in lower_text for x in ["reschedule", "cancel", "can't make", "no show", "skip"]):
            return handle_reschedule_event(profile_name, wa_number, cmd, is_admin=False)

        # ─────────────────────────────
        # LOOKUP CLIENT STATUS
        # ─────────────────────────────
        lookup = {}
        if GAS_WEBHOOK_URL:
            r = requests.post(GAS_WEBHOOK_URL, json={"action": "lookup_client_name", "wa_number": wa_number}, timeout=REQUEST_TIMEOUT)
            lookup = r.json() if r.ok else {}

        if lookup.get("ok"):
            send_client_menu(wa_number, lookup.get("client_name"))
            return jsonify({"status": "client fallback"}), 200

        # guest fallback
        print(f"🙋 Guest detected: {profile_name} ({wa_number})")
        try:
            send_whatsapp_template(wa_number, TEMPLATE_GUEST_WELCOME, TEMPLATE_LANG, [profile_name or "there"])
            print(f"✅ Guest template sent via {TEMPLATE_GUEST_WELCOME}")
        except Exception as e:
            print(f"⚠️ Template send failed ({e}), using text fallback.")
            msg = (
                "🤖 Hello! This is the PilatesHQ Chatbot.\n\n"
                "This WhatsApp number is reserved for *registered clients* "
                "to manage bookings, reminders, and invoices.\n\n"
                "If you’d like to start Pilates or learn more, please contact *Nadine* directly 📱 084 313 1635, "
                "email 📧 lu@pilateshq.co.za, or visit 🌐 www.pilateshq.co.za 💜"
            )
            send_whatsapp_text(wa_number, msg)
        print("✅ Guest politely redirected (no lead created)")
        return jsonify({"status": "guest message"}), 200

    except Exception as e:
        print(f"❌ Webhook processing error: {e}")
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# TEST SEND + HEALTH
# ─────────────────────────────────────────────────────────────
@router_bp.route("/test_send", methods=["POST"])
def test_send():
    try:
        d = request.get_json(force=True)
        send_whatsapp_text(d.get("to"), d.get("text"))
        return jsonify({"ok": True}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@router_bp.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "PilatesHQ Booking Bot"}), 200
