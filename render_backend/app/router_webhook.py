"""
router_webhook.py – Phase 24D (Final Unified Integration)
────────────────────────────────────────────
Handles incoming Meta Webhook events (GET verify + POST messages).

✅ Includes:
 • Extracts contact name from 'contacts'
 • Admin commands:
     - book / suspend / resume        → standing slot management
     - invoice {client}               → single client invoice review
     - unpaid invoices                → full unpaid invoice summary
     - credits                        → unused credits summary
     - export clients / today / week  → GAS PDF export trigger
     - deactivate {client}            → mark client inactive
     - birthdays / birthdays test     → run weekly birthdays digest now
 • Client reschedule detection → now routed via /schedule/mark-reschedule
 • Guest / unknown number welcome flow (no escalation)
────────────────────────────────────────────
"""

import os
import json
import time
import requests
from flask import Blueprint, request, jsonify
from .utils import send_safe_message, send_whatsapp_text

router_bp = Blueprint("router_bp", __name__)

# ── Environment variables ────────────────────────────────────────────────
VERIFY_TOKEN   = os.getenv("META_VERIFY_TOKEN", "")
WEBHOOK_BASE   = os.getenv("WEBHOOK_BASE", "https://pilateshq-booking-bot.onrender.com")
NADINE_WA      = os.getenv("NADINE_WA", "")
TEMPLATE_LANG  = os.getenv("TEMPLATE_LANG", "en_US")

# GAS + internal endpoints
GAS_WEBHOOK_URL   = os.getenv("GAS_WEBHOOK_URL", "")
APPS_SCRIPT_URL   = os.getenv("APPS_SCRIPT_URL", "")
SCHEDULE_ENDPOINT = f"{WEBHOOK_BASE}/schedule/mark-reschedule"   # ← updated
STANDING_ENDPOINT = f"{WEBHOOK_BASE}/tasks/standing/command"
INVOICE_ENDPOINT  = f"{WEBHOOK_BASE}/invoices/review-one"
UNPAID_ENDPOINT   = f"{WEBHOOK_BASE}/invoices/unpaid"


# ───────────────────────────────
# Utility helper
# ───────────────────────────────
def notify_admin(message: str):
    """Send a safe WhatsApp message to Nadine (admin)."""
    try:
        send_safe_message(NADINE_WA, message)
    except Exception as e:
        print(f"⚠️ notify_admin failed: {e}")


# ───────────────────────────────
# META VERIFICATION HANDSHAKE
# ───────────────────────────────
@router_bp.route("/webhook", methods=["GET"])
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("✅ Meta webhook verified successfully.")
        return challenge, 200
    print("❌ Meta webhook verification failed.")
    return "Forbidden", 403


# ───────────────────────────────
# META MESSAGE HANDLER
# ───────────────────────────────
@router_bp.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    print("📩 Webhook received:", data)

    try:
        entry  = (data.get("entry") or [{}])[0]
        change = (entry.get("changes") or [{}])[0]
        value  = change.get("value", {})

        # ── 1️⃣ Status updates ─────────────────────────────
        if "statuses" in value:
            status = value["statuses"][0]
            print(f"📬 Status update: {status.get('id')} → {status.get('status')}")
            return jsonify({"status": "logged"}), 200

        # ── 2️⃣ Incoming messages ─────────────────────────
        if "messages" in value:
            msg        = value["messages"][0]
            wa_number  = msg.get("from", "")
            msg_text   = msg.get("text", {}).get("body", "").strip()
            lower_text = msg_text.lower()
            contacts   = value.get("contacts", [])
            profile_name = contacts[0]["profile"]["name"] if contacts else "Unknown"

            print(f"💬 Message from {profile_name} ({wa_number}): {msg_text}")

            # ───────────────────────────────
            # ⚙️ ADMIN STANDING SLOT COMMANDS
            # ───────────────────────────────
            if wa_number == NADINE_WA and any(lower_text.startswith(c) for c in ["book ", "suspend ", "resume "]):
                try:
                    r = requests.post(STANDING_ENDPOINT, json={"from": wa_number, "text": msg_text}, timeout=10)
                    notify_admin(f"✅ Standing command sent ({r.status_code})")
                except Exception as e:
                    notify_admin(f"⚠️ Standing cmd error: {e}")
                return jsonify({"status": "standing handled"}), 200

            # ───────────────────────────────
            # 🧾 INVOICE COMMAND
            # ───────────────────────────────
            if wa_number == NADINE_WA and lower_text.startswith("invoice "):
                client_name = msg_text.split(" ", 1)[1].strip()
                try:
                    r = requests.post(INVOICE_ENDPOINT, json={"client_name": client_name}, timeout=10)
                    notify_admin(f"✅ Invoice sent for {client_name}")
                except Exception as e:
                    notify_admin(f"⚠️ Invoice error: {e}")
                return jsonify({"status": "invoice handled"}), 200

            # ───────────────────────────────
            # 💰 UNPAID INVOICES
            # ───────────────────────────────
            if wa_number == NADINE_WA and lower_text in ["unpaid invoices", "check invoices"]:
                try:
                    requests.post(UNPAID_ENDPOINT, json={"action": "list_overdue_invoices"}, timeout=15)
                    notify_admin("✅ Unpaid invoices summary requested")
                except Exception as e:
                    notify_admin(f"⚠️ Unpaid request failed: {e}")
                return jsonify({"status": "unpaid handled"}), 200

            # ───────────────────────────────
            # 🧩 EXPORT COMMANDS
            # ───────────────────────────────
            if wa_number == NADINE_WA and lower_text.startswith("export"):
                if not GAS_WEBHOOK_URL:
                    notify_admin("⚠️ GAS webhook not configured.")
                    return jsonify({"status": "missing GAS"}), 200

                action_map = {
                    "clients": ("export_clients", "Clients Register"),
                    "today": ("export_sessions_today", "Today's Sessions"),
                    "week": ("export_sessions_week", "Weekly Sessions"),
                }
                matched = next(((a, l) for k, (a, l) in action_map.items() if k in lower_text), None)
                if not matched:
                    notify_admin("⚠️ Unknown export command.")
                    return jsonify({"status": "unknown export"}), 200

                action, label = matched
                success, pdf_link, response_text = False, None, ""
                for attempt in range(2):
                    try:
                        r = requests.post(GAS_WEBHOOK_URL, json={"action": action}, timeout=25)
                        response_text = r.text
                        if r.ok:
                            data = json.loads(r.text)
                            if data.get("ok") and data.get("pdf_link"):
                                pdf_link = data["pdf_link"]
                                success = True
                                break
                    except Exception as e:
                        print(f"⚠️ Export attempt {attempt+1} failed: {e}")
                    time.sleep(1.2)

                msg = f"✅ {label} ready: {pdf_link}" if success else f"❌ {label} export failed"
                notify_admin(msg)
                return jsonify({"status": "export handled", "ok": success}), 200

            # ───────────────────────────────
            # 📴 DEACTIVATE CLIENT
            # ───────────────────────────────
            if wa_number == NADINE_WA and lower_text.startswith("deactivate "):
                client_name = msg_text.split(" ", 1)[1].strip()
                try:
                    r = requests.post(GAS_WEBHOOK_URL, json={"action": "deactivate_client", "client_name": client_name}, timeout=20)
                    if r.ok and json.loads(r.text).get("ok"):
                        notify_admin(f"✅ Deactivated: {client_name}")
                    else:
                        notify_admin(f"⚠️ Could not deactivate {client_name}")
                except Exception as e:
                    notify_admin(f"❌ Deactivate error: {e}")
                return jsonify({"status": "deactivate handled"}), 200

            # ───────────────────────────────
            # 🎂 BIRTHDAYS DIGEST
            # ───────────────────────────────
            if wa_number == NADINE_WA and lower_text in ["birthdays", "birthdays test"]:
                try:
                    r = requests.post(GAS_WEBHOOK_URL, json={"action": "weekly_birthdays_digest"}, timeout=30)
                    if r.ok:
                        data = json.loads(r.text)
                        summary = data.get("summary", "No birthdays this week.")
                        notify_admin(f"🎂 Birthdays digest: {summary}")
                    else:
                        notify_admin("❌ Birthdays digest failed")
                except Exception as e:
                    notify_admin(f"❌ Digest error: {e}")
                return jsonify({"status": "birthdays handled"}), 200

            # ───────────────────────────────
            # 🔁 CLIENT RESCHEDULE
            # ───────────────────────────────
            if "reschedule" in lower_text:
                try:
                    requests.post(
                        SCHEDULE_ENDPOINT,
                        json={"client_name": profile_name},
                        timeout=6
                    )
                    notify_admin(f"🔁 Reschedule noted for {profile_name}")
                except Exception as e:
                    print(f"⚠️ Reschedule forward failed: {e}")
                return jsonify({"status": "reschedule handled"}), 200

            # ───────────────────────────────
            # 📊 CREDITS SUMMARY
            # ───────────────────────────────
            if lower_text in ["credits", "unused credits"]:
                if APPS_SCRIPT_URL:
                    try:
                        requests.post(APPS_SCRIPT_URL, json={"action": "get_unused_credits"}, timeout=10)
                        notify_admin("✅ Credits summary requested")
                    except Exception as e:
                        notify_admin(f"⚠️ Credits request failed: {e}")
                return jsonify({"status": "credits handled"}), 200

            # ───────────────────────────────
            # 🌐 GUEST HANDLING
            # ───────────────────────────────
            print(f"🙋 Guest contacted bot: {profile_name} ({wa_number})")
            welcome = (
                "🤖 Hello! This is the *PilatesHQ Chatbot.*\n\n"
                "This WhatsApp number is reserved for *registered clients* "
                "to manage bookings, reminders, and invoices.\n\n"
                "If you’d like to start Pilates or learn more, please contact *Nadine* via "
                "email at 📧 *lu@pilateshq.co.za* or visit our website 🌐 *www.pilateshq.co.za* 💜"
            )
            try:
                send_whatsapp_text(wa_number, welcome)
            except Exception as e:
                print(f"⚠️ Guest welcome failed → {e}")
            return jsonify({"status": "guest redirect"}), 200

        print("⚠️ Unknown event type:", value)
        return jsonify({"status": "ignored"}), 200

    except Exception as e:
        print("❌ Webhook error:", e)
        return jsonify({"error": str(e)}), 500


# ───────────────────────────────
# HEALTH CHECK
# ───────────────────────────────
@router_bp.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "PilatesHQ Booking Bot"}), 200
