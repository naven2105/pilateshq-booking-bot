#app/router_webhook.py
"""
router_webhook.py
────────────────────────────────────────────
Handles incoming Meta Webhook events (GET verify + POST messages).

✅ Updates:
 • Extracts contact name from 'contacts' → no more "Unknown"
 • Removes internal loopback timeout (no self-call hang)
 • Simplifies admin alert text (no line breaks)
────────────────────────────────────────────
"""

import os
import requests
from flask import Blueprint, request, jsonify
from .admin_nudge import notify_new_lead
from .utils import send_whatsapp_template

router_bp = Blueprint("router_bp", __name__)

# ── Environment variables ────────────────────────────────────────────────
VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "")
WEBHOOK_BASE = os.getenv("WEBHOOK_BASE", "https://pilateshq-booking-bot.onrender.com")
NADINE_WA = os.getenv("NADINE_WA", "")
TEMPLATE_LANG = os.getenv("TEMPLATE_LANG", "en_US")
ATTENDANCE_ENDPOINT = f"{WEBHOOK_BASE}/attendance/log"
APPS_SCRIPT_URL = os.getenv("APPS_SCRIPT_URL", "")


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
        entry = (data.get("entry") or [{}])[0]
        change = (entry.get("changes") or [{}])[0]
        value = change.get("value", {})

        # ── 1️⃣ Status updates ─────────────────────────────────────────
        if "statuses" in value:
            status = value["statuses"][0]
            print(f"📬 Status update: {status.get('id')} → {status.get('status')}")
            return jsonify({"status": "logged"}), 200

        # ── 2️⃣ Incoming messages ─────────────────────────────────────
        if "messages" in value:
            msg = value["messages"][0]
            wa_number = msg.get("from", "")
            msg_text = msg.get("text", {}).get("body", "").strip()
            lower_text = msg_text.lower()

            # ✅ Extract client name correctly from 'contacts'
            contacts = value.get("contacts", [])
            profile_name = contacts[0]["profile"]["name"] if contacts else "Unknown"

            print(f"💬 Incoming message from {profile_name} ({wa_number}): {msg_text}")

            # ────────────────────────────────────────────────────────────
            # 🔁 Handle RESCHEDULE only
            # ────────────────────────────────────────────────────────────
            if "reschedule" in lower_text:
                print(f"🔁 Attendance event from {profile_name} ({wa_number}) → reschedule")

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

                send_whatsapp_template(
                    to=wa_number,
                    name="admin_generic_alert_us",
                    lang=TEMPLATE_LANG,
                    variables=["Fetching latest credits summary..."],
                )

                if APPS_SCRIPT_URL:
                    try:
                        requests.post(APPS_SCRIPT_URL, json={"action": "get_unused_credits"}, timeout=10)
                    except Exception as e:
                        print(f"❌ Failed to request unused credits → {e}")

                return jsonify({"status": "credits summary requested"}), 200

            # ────────────────────────────────────────────────────────────
            # Default → treat as new lead
            # ────────────────────────────────────────────────────────────
            notify_new_lead(name=profile_name, wa_number=wa_number)
            return jsonify({"status": "new lead handled"}), 200

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
