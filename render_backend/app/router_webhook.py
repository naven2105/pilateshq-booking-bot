"""
router_webhook.py
Handles incoming Meta Webhook events (GET verify + POST messages).
Forwards “RESCHEDULE” to Google Apps Script and triggers admin notifications.
"""

import os
import requests
from flask import Blueprint, request, jsonify
from render_backend.app.admin_nudge import notify_new_lead
from render_backend.app.utils import send_whatsapp_template

router_bp = Blueprint("router_bp", __name__)

VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
APPS_SCRIPT_URL = f"https://script.googleapis.com/v1/scripts/{GOOGLE_API_KEY}:run"


# ───────────────────────────────
# META VERIFICATION HANDSHAKE
# ───────────────────────────────
@router_bp.route("/webhook", methods=["GET"])
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403


# ───────────────────────────────
# META MESSAGE HANDLER
# ───────────────────────────────
@router_bp.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    print("📩 Webhook received:", data)

    try:
        entry = data.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        message = changes["value"]["messages"][0]
        wa_number = message["from"]
        msg_text = message["text"]["body"].strip().lower()

        # Forward RESCHEDULE to Apps Script
        if "reschedule" in msg_text:
            requests.post(APPS_SCRIPT_URL, json={"function": "handleReschedule", "parameters": [wa_number]})
            return jsonify({"status": "forwarded to Apps Script"}), 200

        # Treat unknown numbers as new leads
        if msg_text not in ("hi", "hello"):
            notify_new_lead(name="Unknown", wa_number=wa_number)

        return jsonify({"status": "processed"}), 200

    except Exception as e:
        print("❌ Webhook error:", e)
        return jsonify({"error": str(e)}), 500
