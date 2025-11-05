"""
router_webhook.py – Phase 26D (Interactive Button Fix + Lean Logging + GAS Integration)
────────────────────────────────────────────────────────────
Handles all incoming Meta Webhook events (GET verify + POST messages).

✅ Includes:
 • Extracts contact name from ‘contacts’
 • Detects interactive button payloads (MY_SCHEDULE, etc.)
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
from .client_menu_router import send_client_menu, handle_client_action as handle_client_action_inner

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
# Helper: Extract text or button payload from a message
# ─────────────────────────────────────────────────────────────
def extract_message_text(msg: dict) -> str:
    """
    Safely extract the user's intent text from WhatsApp webhook message.

    Supports both:
      • Standard text messages  → msg["text"]["body"]
      • Interactive button replies → msg["interactive"]["button_reply"]["id"]
      • List replies → msg["interactive"]["list_reply"]["id"]

    Returns a clean uppercase payload string (e.g., "MY_SCHEDULE").
    """
    try:
        mtype = msg.get("type", "")
        if mtype == "text":
            return msg.get("text", {}).get("body", "").strip()
        if mtype == "interactive":
            interactive = msg.get("interactive", {})
            if "button_reply" in interactive:
                return interactive["button_reply"].get("id", "").strip()
            if "list_reply" in interactive:
                return interactive["list_reply"].get("id", "").strip()
        return ""
    except Exception:
        return ""


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

    # ── Lean Logging ───────────────────────────────────────────
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
                summary = extract_message_text(msg)
                contacts = value.get("contacts", [])
                profile = contacts[0]["profile"]["name"] if contacts else "Unknown"
                print(f"💬 {profile} ({wa_number}) → {summary}")
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
        msg_text = extract_message_text(msg)
        lower_text = msg_text.lower()
        contacts = value.get("contacts", [])
        profile_name = contacts[0]["profile"]["name"] if contacts else "Unknown"

        # ─────────────────────────────
        # ADMIN COMMANDS (Nadine only)
        # ─────────────────────────────
        if wa_number == NADINE_WA:
            if any(lower_text.startswith(c) for c in ["book ", "suspend ", "resume "]):
                try:
                    r = requests.post(STANDING_ENDPOINT, json={"from": wa_number, "text": msg_text}, timeout=10)
                    notify_admin(f"Standing command processed ({r.status_code})")
                except Exception as e:
                    notify_admin(f"Standing command error: {e}")
                return jsonify({"status": "standing handled"}), 200

            if lower_text.startswith("invoice "):
                client_name = msg_text.split(" ", 1)[1].strip()
                try:
                    requests.post(INVOICE_ENDPOINT, json={"client_name": client_name}, timeout=10)
                    notify_admin(f"Invoice sent for {client_name}")
                except Exception as e:
                    notify_admin(f"Invoice error: {e}")
                return jsonify({"status": "invoice handled"}), 200

            if lower_text in ["unpaid invoices", "check invoices"]:
                try:
                    requests.post(UNPAID_ENDPOINT, json={"action": "list_overdue_invoices"}, timeout=15)
                    notify_admin("Unpaid invoices summary requested")
                except Exception as e:
                    notify_admin(f"Unpaid request failed: {e}")
                return jsonify({"status": "unpaid handled"}), 200

            if lower_text.startswith("export"):
                if not GAS_WEBHOOK_URL:
                    notify_admin("GAS webhook not configured.")
                    return jsonify({"status": "missing GAS"}), 200
                mapping = {
                    "clients": ("export_clients", "Clients Register"),
                    "today": ("export_sessions_today", "Today's Sessions"),
                    "week": ("export_sessions_week", "Weekly Sessions"),
                }
                matched = next(((a, l) for k, (a, l) in mapping.items() if k in lower_text), None)
                if not matched:
                    notify_admin("Unknown export command.")
                    return jsonify({"status": "unknown export"}), 200
                action, label = matched
                try:
                    r = requests.post(GAS_WEBHOOK_URL, json={"action": action}, timeout=25)
                    if r.ok and r.json().get("ok"):
                        notify_admin(f"{label} export completed successfully.")
                    else:
                        notify_admin(f"{label} export failed.")
                except Exception as e:
                    notify_admin(f"Export error: {e}")
                return jsonify({"status": "export handled"}), 200

            if lower_text.startswith("deactivate "):
                client_name = msg_text.split(" ", 1)[1].strip()
                try:
                    r = requests.post(GAS_WEBHOOK_URL, json={"action": "deactivate_client", "client_name": client_name}, timeout=20)
                    if r.ok and r.json().get("ok"):
                        notify_admin(f"Deactivated {client_name}")
                    else:
                        notify_admin(f"Could not deactivate {client_name}")
                except Exception as e:
                    notify_admin(f"Deactivate error: {e}")
                return jsonify({"status": "deactivate handled"}), 200

            if lower_text in ["birthdays", "birthdays test"]:
                try:
                    r = requests.post(GAS_WEBHOOK_URL, json={"action": "weekly_birthdays_digest"}, timeout=30)
                    notify_admin("🎂 Birthdays digest completed." if r.ok else "Birthdays digest failed.")
                except Exception as e:
                    notify_admin(f"Digest error: {e}")
                return jsonify({"status": "birthdays handled"}), 200

            send_whatsapp_template(
                wa_number,
                "admin_generic_alert_us",
                TEMPLATE_LANG,
                [f"You sent '{msg_text}'. Here's your admin quick menu reminder."]
            )
            return jsonify({"status": "admin fallback"}), 200


        # ─────────────────────────────
        # CLIENT MENU / ACTIONS
        # ─────────────────────────────
        if msg_text.upper() in ["MY_SCHEDULE", "CHECK_AVAILABILITY", "VIEW_LATEST_INVOICE"]:
            try:
                payload = {
                    "wa_number": wa_number,
                    "name": profile_name,
                    "payload": msg_text.upper().strip(),
                }
                handle_client_action_inner(payload)
                return jsonify({"status": "client action handled", "payload": msg_text}), 200
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
        lookup = {}
        if GAS_WEBHOOK_URL:
            try:
                r = requests.post(GAS_WEBHOOK_URL, json={"action": "lookup_client_name", "wa_number": wa_number}, timeout=10)
                lookup = r.json() if r.ok else {}
            except Exception as e:
                print(f"⚠️ GAS lookup failed: {e}")

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
                [profile_name or "there"],
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
