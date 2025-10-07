"""
router_webhook.py
────────────────────────────────────────────
Handles incoming Meta Webhook events (GET verify + POST messages).
Forwards “RESCHEDULE” to Google Apps Script and triggers admin notifications.
"""

import os
import requests
from flask import Blueprint, request, jsonify
from render_backend.app.admin_nudge import notify_new_lead

router_bp = Blueprint("router_bp", __name__)

VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
APPS_SCRIPT_URL = f"https://script.googleapis.com/v1/scripts/{GOOGLE_API_KEY}:run"


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
        # Validate expected structure
        entry = (data.get("entry") or [{}])[0]
        change = (entry.get("changes") or [{}])[0]
        value = change.get("value", {})

        # ── Case 1: Status update (sent, delivered, failed) ────────────────
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

        # ── Case 2: New incoming message ──────────────────────────────────
        if "messages" in value:
            msg = value["messages"][0]
            wa_number = msg.get("from", "")
            msg_text = msg.get("text", {}).get("body", "").strip().lower()

            print(f"💬 Incoming message from {wa_number}: {msg_text}")

            # Forward RESCHEDULE requests to Apps Script
            if "reschedule" in msg_text:
                payload = {"function": "handleReschedule", "parameters": [wa_number]}
                requests.post(APPS_SCRIPT_URL, json=payload)
                print(f"🔁 Forwarded 'reschedule' to Apps Script for {wa_number}")
                return jsonify({"status": "forwarded"}), 200

            # Notify Nadine for new lead
            notify_new_lead(name="Unknown", wa_number=wa_number)
            return jsonify({"status": "message processed"}), 200

        # ── Case 3: Unknown event type ────────────────────────────────────
        print("⚠️ Unknown webhook event type received:", value)
        return jsonify({"status": "ignored"}), 200

    except Exception as e:
        print("❌ Webhook error:", e)
        return jsonify({"error": str(e)}), 500
