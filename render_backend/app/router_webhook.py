#app/router_webhook.py
"""
Main Flask Webhook Router — Database-Free Version
-------------------------------------------------
Handles all incoming WhatsApp messages:
• Detects RESCHEDULE replies
• Forwards them to Google Apps Script
• Sends confirmations & admin alerts
• Looks up client names via Google Sheets API (no Postgres required)
"""

import os
import json
import logging
import requests
from flask import Blueprint, request, current_app, jsonify
from .utils import send_whatsapp_text
from .admin_nudge import notify_new_lead
from .reschedule_forwarder import forward_reschedule

router_bp = Blueprint("router_bp", __name__)
log = logging.getLogger(__name__)

# ─── Environment Variables ────────────────────────────────────────
META_VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "")
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "")
GOOGLE_SHEET_ID = os.getenv("CLIENT_SHEET_ID", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")  # for Sheets API public access

# ─────────────────────────────────────────────────────────────
# 🔐 Meta Webhook Verification (GET)
# ─────────────────────────────────────────────────────────────
@router_bp.route("/webhook", methods=["GET"])
def verify_token():
    verify_token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if verify_token == META_VERIFY_TOKEN:
        log.info("[Webhook] Verified successfully.")
        return challenge, 200
    log.warning("[Webhook] Verification failed.")
    return "Forbidden", 403


# ─────────────────────────────────────────────────────────────
# 📄 Google Sheets Client Name Lookup
# ─────────────────────────────────────────────────────────────
def lookup_client_name(wa_number: str):
    """
    Looks up client name from Google Sheets instead of Postgres.
    Sheet structure:
      Column A = Name
      Column B = WhatsApp number (e.g., 27735534607)
    """
    if not GOOGLE_SHEET_ID or not GOOGLE_API_KEY:
        log.warning("[Lookup] Missing Google Sheet config.")
        return "Unknown"

    try:
        url = (
            f"https://sheets.googleapis.com/v4/spreadsheets/{GOOGLE_SHEET_ID}/values/"
            f"PilatesHQ Clients!A:B?key={GOOGLE_API_KEY}"
        )
        res = requests.get(url, timeout=10)
        res.raise_for_status()
        values = res.json().get("values", [])[1:]  # skip header
        for row in values:
            if len(row) >= 2 and row[1].replace(" ", "") == wa_number:
                return row[0]
        return "Unknown"
    except Exception as e:
        log.error(f"[Lookup] Failed: {e}")
        return "Unknown"


# ─────────────────────────────────────────────────────────────
# 📩 Incoming Message Handler (POST)
# ─────────────────────────────────────────────────────────────
@router_bp.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    if not data:
        return "No data", 400

    log.info(f"[Webhook] Incoming payload: {json.dumps(data)[:400]}")

    try:
        changes = data.get("entry", [])[0].get("changes", [])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])
        if not messages:
            return "ok", 200

        msg = messages[0]
        from_number = msg.get("from")
        msg_type = msg.get("type")
        text_body = (msg.get("text", {}).get("body") or "").strip()
        text_upper = text_body.upper()

        log.info(f"[Webhook] From {from_number}: {text_body}")

        # ─── RESCHEDULE detection ─────────────────────────────
        if text_upper == "RESCHEDULE":
            client_name = lookup_client_name(from_number)
            forward_reschedule(client_name, from_number)
            send_whatsapp_text(
                from_number,
                "🔄 Got it! Nadine has been notified and will contact you to reschedule soon 💜",
            )
            return "ok", 200

        # ─── New Prospect or Greeting ─────────────────────────
        if any(x in text_body.lower() for x in ["hi", "hello", "hey"]):
            notify_new_lead(from_number, text_body)
            return "ok", 200

        # ─── Booking command placeholder ──────────────────────
        if text_upper.startswith("BOOK "):
            send_whatsapp_text(
                from_number,
                "📘 Got your booking request — Nadine will confirm shortly!",
            )
            return "ok", 200

        # ─── Default fallback ─────────────────────────────────
        send_whatsapp_text(
            from_number,
            "💬 Thank you! Your message has been received — Nadine will respond soon.",
        )
        return "ok", 200

    except Exception as e:
        log.exception(f"[Webhook] Error: {e}")
        return jsonify({"error": str(e)}), 500
