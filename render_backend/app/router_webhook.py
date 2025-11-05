"""
router_webhook.py – Phase 26D (Interactive Buttons + Lean Logging)
────────────────────────────────────────────────────────────
Handles all incoming Meta Webhook events (GET verify + POST messages).

✅ Includes:
 • Extracts contact name from ‘contacts’
 • Detects text & interactive button replies (MY_SCHEDULE, etc.)
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
import time
import requests
from flask import Blueprint, request, jsonify
from .utils import send_safe_message, send_whatsapp_text, send_whatsapp_template
from .client_reschedule_handler import handle_reschedule_event
from .client_menu_router import send_client_menu, handle_client_action
from .client_menu_router import handle_client_action as handle_client_action_inner

# ─────────────────────────────────────────────────────────────
router_bp = Blueprint("router_bp", __name__)

# ── Environment variables ─────────────────────────────────────
VERIFY_TOKEN      = os.getenv("META_VERIFY_TOKEN", "")
WEBHOOK_BASE      = os.getenv("WEBHOOK_BASE", "https://pilateshq-booking-bot.onrender.com")
NADINE_WA         = os.getenv("NADINE_WA", "")
TEMPLATE_LANG     = os.getenv("TEMPLATE_LANG", "en_US")
TEMPLATE_GUEST_WELCOME = os.getenv("TEMPLATE_GUEST_WELCOME", "guest_welcome_us")
GAS_WEBHOOK_URL   = os.getenv("GAS_WEBHOOK_URL", "")
DEBUG_MODE        = os.getenv("DEBUG_MODE", "false").lower() == "true"

STANDING_ENDPOINT = f"{WEBHOOK_BASE}/tasks/standing/command"
INVOICE_ENDPOINT  = f"{WEBHOOK_BASE}/invoices/review-one"
UNPAID_ENDPOINT   = f"{WEBHOOK_BASE}/invoices/unpaid"


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
# META VERIFICATION HANDSHAKE
# ─────────────────────────────────────────────────────────────
@router_bp.route("/webhook", methods=["GET"])
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("✅ Meta webhook verified.")
        return challenge, 200
    print("❌ Webhook verification failed.")
    return "Forbidden", 403


# ─────────────────────────────────────────────────────────────
# META MESSAGE HANDLER
# ─────────────────────────────────────────────────────────────
@router_bp.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)

    # ── Condensed Logging ─────────────────────────────────────
    if DEBUG_MODE:
        print("📩 Full webhook (DEBUG):", json.dumps(data, indent=2))
    else:
        try:
            entry = (data.get("entry") or [{}])[0]
            change = (entry.get("changes") or [{}])[0]
            value = change.get("value", {})
            if "messages" in value:
                msg = value["messages"][0]
                wa_number = msg.get("from", "")
                mtype = msg.get("type", "")
                if mtype == "interactive":
                    interactive = msg.get("interactive", {})
                    if "button_reply" in interactive:
                        msg_text = interactive["button_reply"]["id"]
                    elif "list_reply" in interactive:
                        msg_text = interactive["list_reply"]["id"]
                    else:
                        msg_text = "(unknown interactive)"
                else:
                    msg_text = msg.get("text", {}).get("body", "")
                profile = value.get("contacts", [{}])[0].get("profile", {}).get("name", "Unknown")
                print(f"💬 {profile} ({wa_number}) → {msg_text}")
            elif "statuses" in value:
                status = value["statuses"][0]
                print(f"📬 {status.get('recipient_id')} → {status.get('status')}")
        except Exception as e:
            print(f"⚠️ Log parse failed: {e}")

    try:
        entry  = (data.get("entry") or [{}])[0]
        change = (entry.get("changes") or [{}])[0]
        value  = change.get("value", {})

        # ── STATUS EVENTS ────────────────────────────────────────
        if "statuses" in value:
            return jsonify({"ok": True, "type": "status"}), 200

        # ── MESSAGE EVENTS ───────────────────────────────────────
        if "messages" not in value:
            return jsonify({"ok": True, "type": "ignored"}), 200

        msg = value["messages"][0]
        wa_number = msg.get("from", "")
        msg_type = msg.get("type", "")
        msg_text = ""

        # ✅ Support both text and interactive button replies
        if msg_type == "text":
            msg_text = msg.get("text", {}).get("body", "").strip()
        elif msg_type == "interactive":
            interactive = msg.get("interactive", {})
            if "button_reply" in interactive:
                msg_text = interactive["button_reply"]["id"]
            elif "list_reply" in interactive:
                msg_text = interactive["list_reply"]["id"]

        lower_text = msg_text.strip().lower()
        contacts = value.get("contacts", [])
        profile_name = contacts[0]["profile"]["name"] if contacts else "Unknown"

        # ─────────────────────────────
        # ADMIN COMMANDS (Nadine only)
        # ─────────────────────────────
        if wa_number == NADINE_WA:
            # ... (no change to admin section)
            # keep your existing admin logic exactly as before
            pass

        # ─────────────────────────────
        # CLIENT MENU / ACTIONS
        # ─────────────────────────────
        # ✅ Handle interactive payloads (buttons)
        if msg_type == "interactive" and msg_text:
            handle_client_action()
            return jsonify({"status": "interactive handled"}), 200

        if msg_type == "interactive" and msg_text:
            action_payload = {
                "wa_number": wa_number,
                "name": profile_name,
                "payload": msg_text.upper().strip(),
            }
            try:
                handle_client_action_inner(action_payload)
                return jsonify({"status": "interactive handled", "payload": msg_text}), 200
            except Exception as e:      
                print(f"⚠️ handle_client_action failed: {e}")
                send_whatsapp_text(wa_number, "⚠️ Sorry, something went wrong processing your selection.")
                return jsonify({"status": "interactive error"}), 500

        if lower_text in ["menu", "help"]:
            send_client_menu(wa_number, profile_name)
            return jsonify({"status": "menu sent"}), 200

        if any(x in lower_text for x in ["reschedule", "cancel", "can't make", "no show", "skip"]):
            return handle_reschedule_event(profile_name, wa_number, msg_text, is_admin=False)

        # ─────────────────────────────
        # LOOKUP CLIENT STATUS IN GAS
        # ─────────────────────────────
        try:
            lookup = {}
            if GAS_WEBHOOK_URL:
                r = requests.post(GAS_WEBHOOK_URL, json={"action": "lookup_client_name", "wa_number": wa_number}, timeout=10)
                lookup = r.json() if r.ok else {}

            if lookup.get("ok"):
                send_client_menu(wa_number, lookup.get("client_name"))
                return jsonify({"status": "client fallback"}), 200

            # ─────────────────────────────
            # Guest flow (unregistered)
            # ─────────────────────────────
            print(f"🙋 Guest detected: {profile_name} ({wa_number})")
            try:
                send_whatsapp_template(
                    wa_number,
                    TEMPLATE_GUEST_WELCOME,
                    TEMPLATE_LANG,
                    [profile_name or "there"]
                )
                print(f"✅ Guest template sent via {TEMPLATE_GUEST_WELCOME} to {wa_number}")
            except Exception as e:
                print(f"⚠️ Template send failed ({e}), using text fallback.")
                guest_msg = (
                    "🤖 Hello! This is the PilatesHQ Chatbot.\n\n"
                    "This WhatsApp number is reserved for *registered clients* "
                    "to manage bookings, reminders, and invoices.\n\n"
                    "If you’d like to start Pilates or learn more, please contact *Nadine* directly 📱 084 313 1635, "
                    "email 📧 lu@pilateshq.co.za, or visit 🌐 www.pilateshq.co.za 💜"
                )
                send_whatsapp_text(wa_number, guest_msg)
            print("✅ Guest politely redirected (no lead created)")
            return jsonify({"status": "guest message"}), 200

        except Exception as e:
            print(f"⚠️ Lookup or guest handling failed: {e}")
            return jsonify({"status": "lookup error"}), 200

    except Exception as e:
        print(f"❌ Webhook processing error: {e}")
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# TEST SEND ROUTE
# ─────────────────────────────────────────────────────────────
@router_bp.route("/test_send", methods=["POST"])
def test_send():
    """Manual send for testing."""
    try:
        data = request.get_json(force=True)
        to = data.get("to")
        text = data.get("text")
        send_whatsapp_text(to, text)
        return jsonify({"ok": True, "sent": to}), 200
    except Exception as e:
        print(f"❌ test_send error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────────────────────────
@router_bp.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "PilatesHQ Booking Bot"}), 200
