#app/router_webhook.py
"""
router_webhook.py
────────────────────────────────────────────
Handles incoming Meta Webhook events (GET verify + POST messages).

✅ Updated for Render + Google Sheets integration:
 • Uses new /attendance/log endpoint for 'reschedule' or 'cancel'
 • Keeps 'credits' command and new lead handling intact
 • Logs all POSTs clearly for audit
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
APPS_SCRIPT_URL = os.getenv("APPS_SCRIPT_URL", "")  # kept for credits job


# ───────────────────────────────
# META VERIFICATION HANDSHAKE
# ───────────────────────────────
@router_bp.route("/webhook", methods=["GET"])
def verify():
    """Verify webhook during Meta setup."""
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
    """Handle incoming messages or status events from Meta."""
    data = request.get_json(force=True)
    print("📩 Webhook received:", data)

    try:
        entry = (data.get("entry") or [{}])[0]
        change = (entry.get("changes") or [{}])[0]
        value = change.get("value", {})

        # ── Case 1: Status update ───────────────────────────────────────
        if "statuses" in value:
            status_info = value["statuses"][0]
            msg_id = status_info.get("id")
            msg_status = status_info.get("status")
            recipient = status_info.get("recipient_id")
            print(f"📬 Status update: {msg_id} → {msg_status} (to {recipient})")

            if status_info.get("errors"):
                for err in status_info["errors"]:
                    print(f"⚠️ WhatsApp Error {err.get('code')}: {err.get('message')}")
                    print(f"   Details: {err.get('error_data', {}).get('details')}")
            return jsonify({"status": "status event logged"}), 200

        # ── Case 2: Incoming message ────────────────────────────────────
        if "messages" in value:
            msg = value["messages"][0]
            wa_number = msg.get("from", "")
            msg_text = msg.get("text", {}).get("body", "").strip()
            name = msg.get("profile", {}).get("name", "Unknown")

            print(f"💬 Incoming message from {wa_number}: {msg_text}")

            lower_text = msg_text.lower()

            # ────────────────────────────────────────────────────────────
            # 🔁 RESCHEDULE or CANCEL
            # ────────────────────────────────────────────────────────────
            if "reschedule" in lower_text or "cancel" in lower_text:
                print(f"🔁 Attendance event from {name} ({wa_number}) → {lower_text}")

                try:
                    payload = {
                        "from": wa_number,
                        "name": name,
                        "message": msg_text,
                    }
                    r = requests.post(f"{WEBHOOK_BASE}/attendance/log", json=payload, timeout=10)
                    print(f"📤 Forwarded to /attendance/log → {r.status_code}")
                except Exception as e:
                    print(f"❌ Attendance forwarding failed → {e}")

                # Admin alert fallback in case backend unreachable
                if NADINE_WA:
                    send_whatsapp_template(
                        to=NADINE_WA,
                        name="admin_generic_alert_us",
                        lang=TEMPLATE_LANG,
                        variables=[f"Client {name} ({wa_number}) requested to {lower_text}."]
                    )
                    print("📲 Sent admin alert to Nadine.")

                return jsonify({"status": "attendance handled"}), 200

            # ────────────────────────────────────────────────────────────
            # 📊  CREDITS / UNUSED CREDITS keyword
            # ────────────────────────────────────────────────────────────
            if lower_text in ["credits", "unused credits"]:
                print("📊 Admin requested live credits summary")

                send_whatsapp_template(
                    to=wa_number,
                    name="admin_generic_alert_us",
                    lang=TEMPLATE_LANG,
                    variables=["Fetching latest credits summary..."]
                )

                if APPS_SCRIPT_URL:
                    try:
                        forward_payload = {"action": "get_unused_credits"}
                        r = requests.post(APPS_SCRIPT_URL, json=forward_payload, timeout=10)
                        print(f"📤 Requested unused credits from Sheets → {r.status_code}")
                    except Exception as e:
                        print(f"❌ Failed to request unused credits → {e}")

                return jsonify({"status": "credits summary requested"}), 200

            # ────────────────────────────────────────────────────────────
            # Default → new lead / unknown message
            # ────────────────────────────────────────────────────────────
            notify_new_lead(name=name, wa_number=wa_number)
            return jsonify({"status": "message processed"}), 200

        # ────────────────────────────────────────────────────────────────
        # Unknown event type
        # ────────────────────────────────────────────────────────────────
        print("⚠️ Unknown webhook event type received:", value)
        return jsonify({"status": "ignored"}), 200

    except Exception as e:
        print("❌ Webhook error:", e)
        return jsonify({"error": str(e)}), 500


# ───────────────────────────────
# HEALTH CHECK ENDPOINT
# ───────────────────────────────
@router_bp.route("/", methods=["GET"])
def health():
    """Simple health check endpoint for Render uptime probe."""
    return jsonify({"status": "ok", "service": "PilatesHQ Booking Bot"}), 200
