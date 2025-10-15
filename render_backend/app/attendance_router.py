"""
attendance_router.py
────────────────────────────────────────────
Handles attendance-related actions:
 - Client-initiated reschedules or cancellations
 - Writes to Reschedules sheet via Apps Script
 - Alerts Nadine and acknowledges client
────────────────────────────────────────────
"""

import logging
import os
import requests
from flask import Blueprint, request, jsonify
from .utils import (
    normalize_wa,
    safe_execute,
    send_whatsapp_text,
    send_whatsapp_template,
)
from .config import WEBHOOK_BASE, TZ_NAME

bp = Blueprint("attendance", __name__, url_prefix="/attendance")
log = logging.getLogger(__name__)

# ── Environment setup ─────────────────────────────────────────────
APPS_SCRIPT_URL = os.getenv("GOOGLE_SHEET_WEBHOOK")  # direct Apps Script endpoint
CLIENT_SHEET_ID = os.getenv("CLIENT_SHEET_ID")
ADMIN_WA = os.getenv("ADMIN_WA", os.getenv("NADINE_WA", ""))

# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
def _post_to_apps_script(payload: dict):
    """POST safely to Google Apps Script WebApp."""
    try:
        resp = requests.post(APPS_SCRIPT_URL, json=payload, timeout=10)
        log.info(f"[AppsScript] POST {payload.get('action')} → {resp.status_code}")
        return resp.json() if resp.text else {}
    except Exception as e:
        log.error(f"❌ Apps Script call failed: {e}")
        return {"ok": False, "error": str(e)}


def _get_next_session(wa_number: str):
    """Ask Apps Script for client's next confirmed session (date/time)."""
    payload = {"action": "get_next_session", "wa_number": wa_number}
    result = _post_to_apps_script(payload)
    if result.get("ok"):
        return result.get("date"), result.get("time")
    log.warning(f"[get_next_session] none found for {wa_number}: {result}")
    return None, None


def _append_reschedule(client_name, wa_number, msg_text, status):
    """Append a record to Reschedules sheet."""
    date, time = _get_next_session(wa_number)
    payload = {
        "action": "append_reschedule",
        "sheet_id": CLIENT_SHEET_ID,
        "client_name": client_name,
        "wa_number": wa_number,
        "date": date or "",
        "time": time or "",
        "message": msg_text,
        "status": status,
    }
    return _post_to_apps_script(payload)


# ─────────────────────────────────────────────────────────────
# POST endpoint from webhook (Render backend)
# ─────────────────────────────────────────────────────────────
@bp.route("/log", methods=["POST"])
def handle_attendance_event():
    """
    Expected payload from webhook handler:
    {
      "from": "<wa_number>",
      "name": "<client_name>",
      "message": "<raw message>"
    }
    """
    try:
        data = request.get_json(force=True)
        wa = normalize_wa(data.get("from", ""))
        msg = (data.get("message") or "").lower().strip()
        name = data.get("name") or "Unknown"

        log.info(f"[ATTENDANCE] {name} ({wa}) → {msg}")

        # ── 1️⃣ Detect intent ───────────────────────────────
        if "reschedule" in msg:
            intent = "reschedule"
            status = "Rescheduled"
        elif "cancel" in msg:
            intent = "cancel"
            status = "Cancelled"
        else:
            return jsonify({"ok": False, "message": "No attendance intent found"})

        # ── 2️⃣ Log to Google Sheet ─────────────────────────
        result = _append_reschedule(name, wa, msg, status)
        ok = result.get("ok", False)

        # ── 3️⃣ Notify Nadine (Admin) ───────────────────────
        admin_msg = (
            f"🔄 Reschedule Alert\n{name} — {wa}\n\"{msg}\""
            if intent == "reschedule"
            else f"❌ Cancel Alert\n{name} — {wa}\n\"{msg}\""
        )
        safe_execute(
            "notify_admin",
            send_whatsapp_template,
            ADMIN_WA,
            "admin_generic_alert_us",  # must exist in WhatsApp templates
            "en_US",
            [admin_msg],
        )

        # ── 4️⃣ Acknowledge client ──────────────────────────
        if ok:
            safe_execute(
                "notify_client",
                send_whatsapp_text,
                wa,
                "✅ We’ve received your request. Nadine will confirm shortly.",
            )
        else:
            safe_execute(
                "notify_client_fail",
                send_whatsapp_text,
                wa,
                "⚠️ Sorry, something went wrong while logging your request. Nadine has been notified.",
            )

        return jsonify({"ok": True, "status": status, "apps_script": result})

    except Exception as e:
        log.error(f"[ATTENDANCE_ERROR] {e}")
        return jsonify({"ok": False, "error": str(e)}), 500
