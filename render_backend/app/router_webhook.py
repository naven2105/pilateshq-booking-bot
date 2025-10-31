"""
router_webhook.py – Phase 23D
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
 • Client reschedule detection
 • Guest / unknown number welcome flow
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
ATTENDANCE_ENDPOINT = f"{WEBHOOK_BASE}/attendance/log"
STANDING_ENDPOINT   = f"{WEBHOOK_BASE}/tasks/standing/command"
INVOICE_ENDPOINT    = f"{WEBHOOK_BASE}/invoices/review-one"
UNPAID_ENDPOINT     = f"{WEBHOOK_BASE}/invoices/unpaid"


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

        # ── Status updates ─────────────────────────────
        if "statuses" in value:
            status = value["statuses"][0]
            print(f"📬 Status update: {status.get('id')} → {status.get('status')}")
            return jsonify({"status": "logged"}), 200

        # ── Incoming messages ─────────────────────────
        if "messages" in value:
            msg        = value["messages"][0]
            wa_number  = msg.get("from", "")
            msg_text   = msg.get("text", {}).get("body", "").strip()
            lower_text = msg_text.lower()

            # Extract contact name
            contacts     = value.get("contacts", [])
            profile_name = contacts[0]["profile"]["name"] if contacts else "Unknown"
            print(f"💬 Message from {profile_name} ({wa_number}): {msg_text}")

            # ───────────────────────────────
            # ⚙️ ADMIN STANDING SLOT COMMANDS
            # ───────────────────────────────
            if (
                wa_number == NADINE_WA
                and any(lower_text.startswith(cmd) for cmd in ["book ", "suspend ", "resume "])
            ):
                print("⚙️ Forwarding standing slot command")
                try:
                    payload = {"from": wa_number, "text": msg_text}
                    r = requests.post(STANDING_ENDPOINT, json=payload, timeout=10)
                    print(f"📤 Standing command forwarded → {r.status_code}")
                except Exception as e:
                    print(f"⚠️ Could not forward standing command: {e}")
                return jsonify({"status": "standing handled"}), 200

            # ───────────────────────────────
            # 🧾 ADMIN INVOICE COMMAND
            # ───────────────────────────────
            if wa_number == NADINE_WA and lower_text.startswith("invoice "):
                client_name = msg_text.split(" ", 1)[1].strip()
                print(f"🧾 Invoice request detected for {client_name}")
                try:
                    r = requests.post(INVOICE_ENDPOINT, json={"client_name": client_name}, timeout=10)
                    print(f"📤 Forwarded invoice review → {r.status_code}")
                except Exception as e:
                    print(f"⚠️ Invoice forward failed: {e}")
                return jsonify({"status": "invoice handled"}), 200

            # ───────────────────────────────
            # 💰 UNPAID INVOICES
            # ───────────────────────────────
            if wa_number == NADINE_WA and lower_text in ["unpaid invoices", "check invoices"]:
                print("💰 Unpaid invoices requested")
                try:
                    requests.post(UNPAID_ENDPOINT, json={"action": "list_overdue_invoices"}, timeout=15)
                except Exception as e:
                    print(f"⚠️ Unpaid invoice request failed: {e}")
                return jsonify({"status": "unpaid handled"}), 200

            # ───────────────────────────────
            # 🧩 EXPORT COMMANDS
            # ───────────────────────────────
            if wa_number == NADINE_WA and lower_text.startswith("export"):
                print(f"🧩 Export command received: {lower_text}")
                if not GAS_WEBHOOK_URL:
                    send_safe_message(NADINE_WA, "⚠️ GAS webhook not configured.")
                    return jsonify({"status": "missing GAS"}), 200

                if "clients" in lower_text:
                    action, label = "export_clients", "Clients Register"
                elif "today" in lower_text:
                    action, label = "export_sessions_today", "Today's Sessions"
                elif "week" in lower_text:
                    action, label = "export_sessions_week", "Weekly Sessions"
                else:
                    send_safe_message(NADINE_WA, "⚠️ Unknown export command.")
                    return jsonify({"status": "unknown export"}), 200

                success, pdf_link, response_text = False, None, ""
                for attempt in range(2):
                    try:
                        r = requests.post(GAS_WEBHOOK_URL, json={"action": action}, timeout=25)
                        response_text = r.text
                        if r.ok:
                            data = json.loads(r.text)
                            if data.get("ok") and data.get("link"):
                                pdf_link = data["link"]
                                success = True
                                break
                    except Exception as e:
                        print(f"⚠️ Export attempt {attempt+1} failed: {e}")
                    time.sleep(1.5)

                if success:
                    send_safe_message(NADINE_WA, f"✅ *Export Complete*\n📂 {label}\n🔗 {pdf_link}")
                    print(f"📤 Export success → {pdf_link}")
                else:
                    send_safe_message(NADINE_WA, f"❌ Export failed for *{label}*\n{response_text}")
                    print(f"❌ Export failure → {response_text}")
                return jsonify({"status": "export handled", "ok": success}), 200

            # ───────────────────────────────
            # 📴 DEACTIVATE CLIENT
            # ───────────────────────────────
            if wa_number == NADINE_WA and lower_text.startswith("deactivate "):
                client_name = msg_text.split(" ", 1)[1].strip()
                print(f"📴 Deactivate request for {client_name}")
                try:
                    r = requests.post(
                        GAS_WEBHOOK_URL,
                        json={"action": "deactivate_client", "client_name": client_name},
                        timeout=20,
                    )
                    if r.ok and json.loads(r.text).get("ok"):
                        send_safe_message(NADINE_WA, f"✅ Deactivated: *{client_name}*")
                    else:
                        send_safe_message(NADINE_WA, f"⚠️ Could not deactivate {client_name}: {r.text}")
                except Exception as e:
                    send_safe_message(NADINE_WA, f"❌ Deactivate error: {e}")
                return jsonify({"status": "deactivate handled"}), 200

            # ───────────────────────────────
            # 🎂 BIRTHDAYS DIGEST
            # ───────────────────────────────
            if wa_number == NADINE_WA and lower_text in ["birthdays", "birthdays test"]:
                print("🎂 Admin requested birthdays digest")
                try:
                    r = requests.post(GAS_WEBHOOK_URL, json={"action": "weekly_birthdays_digest"}, timeout=30)
                    if r.ok:
                        data = json.loads(r.text)
                        if data.get("ok"):
                            summary = data.get("summary", "")
                            send_safe_message(NADINE_WA, f"✅ Birthdays digest triggered\n{summary}")
                        else:
                            send_safe_message(NADINE_WA, f"⚠️ Digest failed: {data}")
                    else:
                        send_safe_message(NADINE_WA, f"❌ Digest failed ({r.status_code})")
                except Exception as e:
                    send_safe_message(NADINE_WA, f"❌ Digest error: {e}")
                return jsonify({"status": "birthdays handled"}), 200

            # ───────────────────────────────
            # 🔁 CLIENT RESCHEDULE
            # ───────────────────────────────
            if "reschedule" in lower_text:
                print(f"🔁 Reschedule from {profile_name} ({wa_number})")
                try:
                    requests.post(ATTENDANCE_ENDPOINT, json={"from": wa_number, "name": profile_name, "message": msg_text}, timeout=5)
                except Exception as e:
                    print(f"⚠️ Could not forward attendance log: {e}")
                return jsonify({"status": "reschedule handled"}), 200

            # ───────────────────────────────
            # 📊 CREDITS SUMMARY
            # ───────────────────────────────
            if lower_text in ["credits", "unused credits"]:
                print("📊 Credits summary requested")
                if APPS_SCRIPT_URL:
                    try:
                        requests.post(APPS_SCRIPT_URL, json={"action": "get_unused_credits"}, timeout=10)
                    except Exception as e:
                        print(f"⚠️ Credits request failed: {e}")
                return jsonify({"status": "credits handled"}), 200

            # ───────────────────────────────
            # 🌐 GUEST HANDLING
            # ───────────────────────────────
            print(f"🙋 Guest detected: {profile_name} ({wa_number})")
            welcome = (
                "👋 Welcome to *PilatesHQ Studio!*\n\n"
                "This WhatsApp number is reserved for *registered clients* "
                "to manage bookings, reminders, and invoices.\n\n"
                "For enquiries or new sign-ups, please contact *Nadine* on *084 313 1635* "
                "or visit 🌐 *pilateshq.co.za* 💜"
            )
            try:
                send_whatsapp_text(wa_number, welcome)
            except Exception as e:
                print(f"⚠️ Guest welcome failed → {e}")
            return jsonify({"status": "guest redirect"}), 200

        # Unknown type
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
