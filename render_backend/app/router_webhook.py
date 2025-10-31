"""
router_webhook.py – Phase 23C
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
     - deactivate {client}            → mark client inactive 🆕
     - birthdays test                 → run weekly birthdays digest now 🆕
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
VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "")
WEBHOOK_BASE = os.getenv("WEBHOOK_BASE", "https://pilateshq-booking-bot.onrender.com")
NADINE_WA = os.getenv("NADINE_WA", "")
TEMPLATE_LANG = os.getenv("TEMPLATE_LANG", "en_US")

# GAS webhooks
GAS_WEBHOOK_URL = os.getenv("GAS_WEBHOOK_URL", "")     # Unified /exec for exports + admin actions
APPS_SCRIPT_URL = os.getenv("APPS_SCRIPT_URL", "")     # Legacy (credits); kept for backward-compat

# Internal endpoints (Render)
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

        # ── 1️⃣ Status updates ─────────────────────────────────────────
        if "statuses" in value:
            status = value["statuses"][0]
            print(f"📬 Status update: {status.get('id')} → {status.get('status')}")
            return jsonify({"status": "logged"}), 200

        # ── 2️⃣ Incoming messages ─────────────────────────────────────
        if "messages" in value:
            msg        = value["messages"][0]
            wa_number  = msg.get("from", "")
            msg_text   = msg.get("text", {}).get("body", "").strip()
            lower_text = msg_text.lower()

            # ✅ Extract contact name
            contacts     = value.get("contacts", [])
            profile_name = contacts[0]["profile"]["name"] if contacts else "Unknown"
            print(f"💬 Message from {profile_name} ({wa_number}): {msg_text}")

            # ────────────────────────────────────────────────────────────
            # ⚙️ ADMIN STANDING SLOT COMMANDS
            # ────────────────────────────────────────────────────────────
            if (
                wa_number == NADINE_WA
                and (
                    lower_text.startswith("book ")
                    or lower_text.startswith("suspend ")
                    or lower_text.startswith("resume ")
                )
            ):
                print(f"⚙️ Forwarding standing slot command → {STANDING_ENDPOINT}")
                try:
                    payload = {"from": wa_number, "text": msg_text}
                    r = requests.post(STANDING_ENDPOINT, json=payload, timeout=10)
                    print(f"📤 Standing command forwarded → {r.status_code} | {r.text}")
                except Exception as e:
                    print(f"⚠️ Could not forward standing command: {e}")
                return jsonify({"status": "standing command handled"}), 200

            # ────────────────────────────────────────────────────────────
            # 🧾 ADMIN INVOICE COMMAND
            # ────────────────────────────────────────────────────────────
            if wa_number == NADINE_WA and lower_text.startswith("invoice "):
                client_name = msg_text.split(" ", 1)[1].strip() if " " in msg_text else ""
                if not client_name:
                    return jsonify({"status": "missing client name"}), 200
                print(f"🧾 Invoice request detected for {client_name}")
                try:
                    payload = {"client_name": client_name}
                    r = requests.post(INVOICE_ENDPOINT, json=payload, timeout=10)
                    print(f"📤 Forwarded invoice review → {r.status_code} | {r.text}")
                except Exception as e:
                    print(f"⚠️ Could not forward invoice review: {e}")
                return jsonify({"status": "invoice command handled"}), 200

            # ────────────────────────────────────────────────────────────
            # 💰 ADMIN UNPAID INVOICES COMMAND
            # ────────────────────────────────────────────────────────────
            if wa_number == NADINE_WA and lower_text in ["unpaid invoices", "check invoices"]:
                print(f"💰 Admin requested unpaid invoices summary → {UNPAID_ENDPOINT}")
                try:
                    payload = {"action": "list_overdue_invoices"}
                    r = requests.post(UNPAID_ENDPOINT, json=payload, timeout=15)
                    print(f"📤 Unpaid invoices forwarded → {r.status_code} | {r.text}")
                except Exception as e:
                    print(f"⚠️ Could not forward unpaid invoices: {e}")
                return jsonify({"status": "unpaid invoices handled"}), 200

            # ────────────────────────────────────────────────────────────
            # 🧩 EXPORT COMMANDS (Clients / Today / Week)
            # ────────────────────────────────────────────────────────────
            if wa_number == NADINE_WA and lower_text.startswith("export"):
                print(f"🧩 Export command received → {lower_text}")

                if not GAS_WEBHOOK_URL:
                    send_safe_message(NADINE_WA, "⚠️ GAS webhook not configured.")
                    return jsonify({"status": "missing GAS URL"}), 200

                # Identify export type
                if "clients" in lower_text:
                    action, label = "export_clients", "Clients Register"
                elif "today" in lower_text:
                    action, label = "export_sessions_today", "Today's Sessions"
                elif "week" in lower_text:
                    action, label = "export_sessions_week", "Weekly Sessions"
                else:
                    send_safe_message(NADINE_WA, "⚠️ Unknown export command.")
                    return jsonify({"status": "unknown export"}), 200

                payload = {"action": action}
                success, response_text, pdf_link = False, "", None

                # Try up to 2 times if timeout or 5xx
                for attempt in range(2):
                    try:
                        r = requests.post(GAS_WEBHOOK_URL, json=payload, timeout=25)
                        response_text = r.text
                        if r.ok:
                            try:
                                data = json.loads(r.text)
                                if data.get("ok") and data.get("pdf_link"):
                                    pdf_link = data["pdf_link"]
                                    success = True
                                    break
                            except Exception:
                                print("⚠️ Could not parse JSON response.")
                        else:
                            print(f"⚠️ GAS responded {r.status_code}")
                    except Exception as e:
                        print(f"❌ Export request failed (attempt {attempt+1}): {e}")
                    time.sleep(1.5)

                # WhatsApp feedback
                if success:
                    msg = f"✅ *Export Complete*\n📂 {label}\n🔗 {pdf_link}"
                    send_safe_message(NADINE_WA, msg)
                    print(f"📤 Export success → {pdf_link}")
                else:
                    msg = (
                        f"❌ Export failed for *{label}*\n"
                        f"Server reply:\n{response_text or 'No response'}"
                    )
                    send_safe_message(NADINE_WA, msg)
                    print(f"❌ Export failure → {response_text}")

                return jsonify({"status": "export handled", "success": success}), 200

            # ────────────────────────────────────────────────────────────
            # 📴 ADMIN: DEACTIVATE CLIENT
            # Usage: "deactivate Mary Smith"
            # ────────────────────────────────────────────────────────────
            if wa_number == NADINE_WA and lower_text.startswith("deactivate "):
                client_name = msg_text.split(" ", 1)[1].strip()
                if not GAS_WEBHOOK_URL:
                    send_safe_message(NADINE_WA, "⚠️ GAS webhook not configured.")
                    return jsonify({"status": "missing GAS URL"}), 200
                try:
                    payload = {"action": "deactivate_client", "client_name": client_name}
                    r = requests.post(GAS_WEBHOOK_URL, json=payload, timeout=20)
                    if r.ok:
                        try:
                            data = json.loads(r.text)
                            if data.get("ok"):
                                send_safe_message(NADINE_WA, f"✅ Deactivated: *{client_name}*")
                            else:
                                send_safe_message(NADINE_WA, f"⚠️ Could not deactivate {client_name}: {data}")
                        except Exception:
                            send_safe_message(NADINE_WA, f"⚠️ Deactivate response not JSON: {r.text}")
                    else:
                        send_safe_message(NADINE_WA, f"❌ Deactivate failed ({r.status_code})")
                except Exception as e:
                    send_safe_message(NADINE_WA, f"❌ Deactivate error: {e}")
                return jsonify({"status": "deactivate handled"}), 200

            # ────────────────────────────────────────────────────────────
            # 🎂 ADMIN: BIRTHDAYS DIGEST (on-demand test)
            # Usage: "birthdays test"
            # ────────────────────────────────────────────────────────────
            if wa_number == NADINE_WA and lower_text == "birthdays test":
                if not GAS_WEBHOOK_URL:
                    send_safe_message(NADINE_WA, "⚠️ GAS webhook not configured.")
                    return jsonify({"status": "missing GAS URL"}), 200
                try:
                    payload = {"action": "weekly_birthdays_digest"}
                    r = requests.post(GAS_WEBHOOK_URL, json=payload, timeout=30)
                    if r.ok:
                        try:
                            data = json.loads(r.text)
                            if data.get("ok"):
                                preview = data.get("summary", "Birthdays digest sent.")
                                send_safe_message(NADINE_WA, f"✅ Birthdays digest triggered\n{preview}")
                            else:
                                send_safe_message(NADINE_WA, f"⚠️ Digest failed: {data}")
                        except Exception:
                            send_safe_message(NADINE_WA, f"⚠️ Digest response not JSON: {r.text}")
                    else:
                        send_safe_message(NADINE_WA, f"❌ Digest failed ({r.status_code})")
                except Exception as e:
                    send_safe_message(NADINE_WA, f"❌ Digest error: {e}")
                return jsonify({"status": "birthdays test handled"}), 200

            # ────────────────────────────────────────────────────────────
            # 🔁 CLIENT RESCHEDULE
            # ────────────────────────────────────────────────────────────
            if "reschedule" in lower_text:
                print(f"🔁 Reschedule event from {profile_name} ({wa_number})")
                try:
                    payload = {"from": wa_number, "name": profile_name, "message": msg_text}
                    r = requests.post(ATTENDANCE_ENDPOINT, json=payload, timeout=5)
                    print(f"📤 Forwarded to /attendance/log → {r.status_code}")
                except Exception as e:
                    print(f"⚠️ Could not forward attendance log: {e}")
                return jsonify({"status": "reschedule handled"}), 200

            # ────────────────────────────────────────────────────────────
            # 📊 Credits / Unused Credits
            # ────────────────────────────────────────────────────────────
            if lower_text in ["credits", "unused credits"]:
                print("📊 Admin requested live credits summary")
                if APPS_SCRIPT_URL:
                    try:
                        requests.post(APPS_SCRIPT_URL, json={"action": "get_unused_credits"}, timeout=10)
                    except Exception as e:
                        print(f"❌ Failed to request credits → {e}")
                return jsonify({"status": "credits summary requested"}), 200

            # ────────────────────────────────────────────────────────────
            # 🌐 Guest / Unknown Number Handling
            # ────────────────────────────────────────────────────────────
            print(f"🙋 Guest detected → {profile_name} ({wa_number})")
            try:
                welcome = (
                    "👋 Welcome to *PilatesHQ Studio!*\n\n"
                    "This WhatsApp number is reserved for *registered clients* "
                    "to manage bookings, reminders, and invoices.\n\n"
                    "For enquiries or new sign-ups, please contact *Nadine* on *084 313 1635* "
                    "or visit 🌐 *pilateshq.co.za* 💜"
                )
                send_whatsapp_text(wa_number, welcome)
                print(f"📤 Guest welcome sent to {wa_number}")
            except Exception as e:
                print(f"⚠️ Guest welcome failed → {e}")

            return jsonify({"status": "guest_redirect"}), 200

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
