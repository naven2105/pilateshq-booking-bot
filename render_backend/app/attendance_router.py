# app/attendance_router.py
"""
attendance_router.py
────────────────────────────────────────────
Purpose: Handles everything related to reschedules and reschedule summaries.
Handles all attendance-related events:
 • Client says “Reschedule” → Logs in Google Sheet
 • Nadine books new session → Auto-closes reschedule (via onEdit trigger)
 • Nadine types “Reschedules” → Lists all open cases
────────────────────────────────────────────
"""

import os
import requests
import logging
from flask import Blueprint, request, jsonify
from .utils import send_whatsapp_template

bp = Blueprint("attendance_bp", __name__)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────
WEBHOOK_BASE = os.getenv("WEBHOOK_BASE", "https://pilateshq-booking-bot.onrender.com")
GOOGLE_SHEET_WEBHOOK = os.getenv("GOOGLE_SHEET_WEBHOOK")
CLIENT_SHEET_ID = os.getenv("CLIENT_SHEET_ID")
NADINE_WA = os.getenv("NADINE_WA")
TEMPLATE_LANG = os.getenv("TEMPLATE_LANG", "en_US")

TPL_CLIENT_ALERT = "client_generic_alert_us"
TPL_ADMIN_ALERT = "admin_generic_alert_us"

# ─────────────────────────────────────────────────────────────
# CLIENT → RESCHEDULE
# ─────────────────────────────────────────────────────────────
@bp.route("/attendance/log", methods=["POST"])
def log_attendance():
    data = request.get_json(force=True)
    wa_number = data.get("from") or data.get("wa_number")
    client_name = data.get("name") or data.get("client_name") or "Unknown"
    message = (data.get("message") or "").strip()

    if "reschedule" not in message.lower():
        return jsonify({"ok": False, "reason": "no reschedule keyword found"}), 400

    # Append to Google Sheet
    payload = {
        "action": "append_reschedule",
        "sheet_id": CLIENT_SHEET_ID,
        "client_name": client_name,
        "wa_number": wa_number,
        "message": message,
    }
    try:
        resp = requests.post(GOOGLE_SHEET_WEBHOOK, json=payload, timeout=10)
        log.info(f"[attendance_router] Sheet append → {resp.status_code} | {resp.text}")
    except Exception as e:
        log.error(f"[attendance_router] Failed to append to Google Sheet: {e}")

    # Notify client
    send_whatsapp_template(
        to=wa_number,
        name=TPL_CLIENT_ALERT,
        lang=TEMPLATE_LANG,
        variables=[f"Hi {client_name}, we’ve received your reschedule request. Nadine will confirm a new time soon 🤸‍♀️"],
    )

    # Notify admin
    send_whatsapp_template(
        to=NADINE_WA,
        name=TPL_ADMIN_ALERT,
        lang=TEMPLATE_LANG,
        variables=[f"Client {client_name} ({wa_number}) requested to reschedule."],
    )

    return jsonify({"ok": True, "action": "reschedule"})


# ─────────────────────────────────────────────────────────────
# ADMIN → LIST OPEN RESCHEDULES
# ─────────────────────────────────────────────────────────────
@bp.route("/attendance/list", methods=["POST"])
def list_open_reschedules():
    """Triggered when Nadine types 'Reschedules' on WhatsApp."""
    try:
        payload = {"action": "list_open_reschedules", "sheet_id": CLIENT_SHEET_ID}
        resp = requests.post(GOOGLE_SHEET_WEBHOOK, json=payload, timeout=10)
        result = resp.json() if resp.ok else {"ok": False, "error": "Sheet request failed"}
        message = result.get("message", "⚠️ Could not fetch list")

        send_whatsapp_template(
            to=NADINE_WA,
            name=TPL_ADMIN_ALERT,
            lang=TEMPLATE_LANG,
            variables=[message],
        )
        return jsonify({"ok": True, "message": message})
    except Exception as e:
        log.error(f"[attendance_router] list_open_reschedules error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────────────────────────
@bp.route("/attendance", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "Attendance Router"}), 200
