# render_backend/app/router_webhook.py
"""
router_webhook.py
────────────────────────────────────────────
Handles incoming Meta Webhook events (GET verify + POST messages).
Supports admin commands:
  - "reschedule"
  - "credits"
  - "today"
  - "pause"
  - "resume"
  - "report"
"""

import os
import requests
from flask import Blueprint, request, jsonify
from render_backend.app.admin_nudge import notify_new_lead
from render_backend.app.utils import send_whatsapp_template

router_bp = Blueprint("router_bp", __name__)

# ── Environment variables ───────────────────────────────
VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "")
APPS_SCRIPT_URL = os.getenv("APPS_SCRIPT_URL", "")
NADINE_WA = os.getenv("NADINE_WA", "")
TEMPLATE_LANG = os.getenv("TEMPLATE_LANG", "en_US")

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

        # ── Case 1: Status update ───────────────────────────────
        if "statuses" in value:
            status_info = value["statuses"][0]
            msg_id = status_info.get("id")
            msg_status = status_info.get("status")
            recipient = status_info.get("recipient_id")

            print(f"📬 Status update: {msg_id} → {msg_status} (to {recipient})")
            return jsonify({"status": "status event logged"}), 200

        # ── Case 2: New incoming message ────────────────────────
        if "messages" in value:
            msg = value["messages"][0]
            wa_number = msg.get("from", "")
            msg_text = msg.get("text", {}).get("body", "").strip().lower()
            name = msg.get("profile", {}).get("name", "Unknown")

            print(f"💬 Incoming message from {wa_number}: {msg_text}")

            # ── Handle "reschedule" ─────────────────────────────
            if "reschedule" in msg_text:
                print(f"🔁 Reschedule request from {name} ({wa_number})")
                if APPS_SCRIPT_URL:
                    try:
                        requests.post(APPS_SCRIPT_URL, json={"wa_number": wa_number, "name": name, "message": msg_text}, timeout=10)
                    except Exception as e:
                        print(f"❌ Failed to forward RESCHEDULE → {e}")

                if NADINE_WA:
                    send_whatsapp_template(
                        to=NADINE_WA,
                        name="admin_generic_alert_us",
                        lang=TEMPLATE_LANG,
                        variables=[f"Client {name} ({wa_number}) requested to reschedule."]
                    )
                return jsonify({"status": "reschedule handled"}), 200

            # ── Handle "credits" ────────────────────────────────
            if msg_text in ["credits", "unused credits"]:
                if APPS_SCRIPT_URL:
                    try:
                        requests.post(APPS_SCRIPT_URL, json={"action": "get_unused_credits"}, timeout=10)
                        print("📤 Requested unused credits summary.")
                    except Exception as e:
                        print(f"❌ Failed to request unused credits → {e}")

                send_whatsapp_template(
                    to=wa_number,
                    name="admin_generic_alert_us",
                    lang=TEMPLATE_LANG,
                    variables=["Fetching latest credits summary..."]
                )
                return jsonify({"status": "credits requested"}), 200

            # ── Handle "today" ───────────────────────────────────
            if msg_text in ["today", "bookings today"]:
                if APPS_SCRIPT_URL:
                    try:
                        requests.post(APPS_SCRIPT_URL, json={"action": "get_todays_bookings"}, timeout=10)
                        print("📤 Requested today's bookings.")
                    except Exception as e:
                        print(f"❌ Failed to request today's bookings → {e}")

                send_whatsapp_template(
                    to=wa_number,
                    name="admin_generic_alert_us",
                    lang=TEMPLATE_LANG,
                    variables=["Fetching today's schedule..."]
                )
                return jsonify({"status": "today requested"}), 200

            # ── Handle "pause" / "resume" ─────────────────────────
            if msg_text in ["pause", "resume"]:
                action = "pause_jobs" if msg_text == "pause" else "resume_jobs"
                if APPS_SCRIPT_URL:
                    try:
                        requests.post(APPS_SCRIPT_URL, json={"action": action}, timeout=10)
                        print(f"📤 Sent {action} to Apps Script")
                    except Exception as e:
                        print(f"❌ Failed to send {action} → {e}")

                send_whatsapp_template(
                    to=wa_number,
                    name="admin_generic_alert_us",
                    lang=TEMPLATE_LANG,
                    variables=[f"Automation {msg_text}d successfully."]
                )
                return jsonify({"status": f"{msg_text}d"}), 200

            # ── Handle "report" ───────────────────────────────────
            if msg_text == "report":
                if APPS_SCRIPT_URL:
                    try:
                        requests.post(APPS_SCRIPT_URL, json={"action": "get_admin_report"}, timeout=10)
                        print("📤 Requested admin report from Sheets.")
                    except Exception as e:
                        print(f"❌ Failed to request report → {e}")

                send_whatsapp_template(
                    to=wa_number,
                    name="admin_generic_alert_us",
                    lang=TEMPLATE_LANG,
                    variables=["Generating today's studio report..."]
                )
                return jsonify({"status": "report requested"}), 200

            # ── Default: treat as new lead ───────────────────────
            notify_new_lead(name="Unknown", wa_number=wa_number)
            return jsonify({"status": "message processed"}), 200

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
