# render_backend/app/attendance_router.py
"""
attendance_router.py
────────────────────────────────────────────
Handles client attendance actions such as reschedule or cancellations.
Simplified Reschedule Workflow with Date/Time + Handled columns.
────────────────────────────────────────────
"""

import os
import pytz
import logging
import requests
import datetime
from flask import Blueprint, request, jsonify
from .utils import send_whatsapp_template

# ── Setup ──────────────────────────────────────────────────────
bp = Blueprint("attendance_bp", __name__)
log = logging.getLogger(__name__)

# ── Environment configuration ──────────────────────────────────
NADINE_WA = os.getenv("NADINE_WA", "")
TEMPLATE_LANG = os.getenv("TEMPLATE_LANG", "en_US")
CLIENT_SHEET_ID = os.getenv("CLIENT_SHEET_ID")        # ✅ Your PilatesHQ sheet
GOOGLE_SHEET_WEBHOOK = os.getenv("GOOGLE_SHEET_WEBHOOK")  # ✅ Apps Script WebApp URL
TZ_NAME = os.getenv("TZ_NAME", "Africa/Johannesburg")     # ✅ Local timezone

# ── Templates ──────────────────────────────────────────────────
TPL_CLIENT_ALERT = "client_generic_alert_us"
TPL_ADMIN_ALERT = "admin_generic_alert_us"


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
def _now_local() -> str:
    tz = pytz.timezone(TZ_NAME)
    return datetime.datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")


def _notify_client(wa_number: str, client_name: str):
    """Notify client that reschedule request was received."""
    send_whatsapp_template(
        to=wa_number,
        name=TPL_CLIENT_ALERT,
        lang=TEMPLATE_LANG,
        variables=[
            f"Hi {client_name}, we’ve received your reschedule request. Nadine will confirm a new time soon 🤸‍♀️"
        ],
    )


def _notify_admin(client_name: str, date: str, time: str, message: str):
    """Notify Nadine of a new reschedule request."""
    if not NADINE_WA:
        log.warning("⚠️ NADINE_WA not configured.")
        return

    alert = f"🔄 *Reschedule Request*\n{client_name} — {date} {time}\n“{message}”"
    send_whatsapp_template(
        to=NADINE_WA,
        name=TPL_ADMIN_ALERT,
        lang=TEMPLATE_LANG,
        variables=[alert],
    )


def _append_to_sheet(client_name: str, wa_number: str, date: str, time: str, message: str):
    """Append reschedule record to Google Sheets via Apps Script."""
    if not GOOGLE_SHEET_WEBHOOK:
        log.warning("⚠️ GOOGLE_SHEET_WEBHOOK not configured.")
        return

    payload = {
        "action": "append_reschedule",
        "sheet_id": CLIENT_SHEET_ID,
        "client_name": client_name,
        "wa_number": wa_number,
        "date": date,
        "time": time,
        "message": message,
        "timestamp": _now_local(),
        "status": "Rescheduled",
        "handled": "Open",
    }

    try:
        resp = requests.post(GOOGLE_SHEET_WEBHOOK, json=payload, timeout=10)
        log.info(f"[attendance_router] Sheet append → {resp.status_code} | {resp.text}")
    except Exception as e:
        log.error(f"[attendance_router] Failed to append to Google Sheet: {e}")


# ─────────────────────────────────────────────────────────────
# ROUTE: /attendance/process
# Called when client sends a WhatsApp reschedule message
# ─────────────────────────────────────────────────────────────
@bp.route("/attendance/process", methods=["POST"])
def process_attendance():
    data = request.get_json(force=True)
    log.info(f"[attendance_router] Incoming payload: {data}")

    wa_number = data.get("wa_number")
    client_name = data.get("client_name")
    session_date = data.get("session_date")
    session_time = data.get("session_time")
    message = (data.get("message") or "").strip()

    if not wa_number or not client_name or not session_date or not session_time:
        return jsonify({"ok": False, "error": "Missing required fields"}), 400

    if "reschedule" in message.lower():
        log.info(f"[attendance_router] Logging reschedule for {client_name}")
        _append_to_sheet(client_name, wa_number, session_date, session_time, message)
        _notify_client(wa_number, client_name)
        _notify_admin(client_name, session_date, session_time, message)
        return jsonify({"ok": True, "action": "reschedule"})

    return jsonify({"ok": False, "reason": "no reschedule keyword found"}), 400


# ─────────────────────────────────────────────────────────────
# ROUTE: /attendance/reschedules (Admin command “Reschedules”)
# ─────────────────────────────────────────────────────────────
@bp.route("/attendance/reschedules", methods=["GET"])
def get_open_reschedules():
    payload = {"action": "get_reschedules"}
    try:
        resp = requests.post(GOOGLE_SHEET_WEBHOOK, json=payload, timeout=10)
        rows = resp.json() if resp.ok else []
    except Exception as e:
        log.error(f"[attendance_router] Failed to fetch reschedules: {e}")
        rows = []

    open_items = [r for r in rows if r.get("handled", "").lower() == "open"]

    if not open_items:
        msg = "✅ No open reschedules at the moment."
    else:
        lines = [f"• {r['client']} — {r['date']} {r['time']}" for r in open_items]
        msg = f"🌙 You have {len(open_items)} reschedules to manage:\n" + "\n".join(lines)

    send_whatsapp_template(
        to=NADINE_WA,
        name=TPL_ADMIN_ALERT,
        lang=TEMPLATE_LANG,
        variables=[msg],
    )

    return jsonify({"ok": True, "count": len(open_items)})


# ─────────────────────────────────────────────────────────────
# ROUTE: /attendance/close (Admin command “Close <name>”)
# ─────────────────────────────────────────────────────────────
@bp.route("/attendance/close", methods=["POST"])
def close_reschedule():
    data = request.get_json(force=True)
    client_name = data.get("client_name")

    if not client_name:
        return jsonify({"ok": False, "error": "Missing client name"}), 400

    payload = {"action": "close_reschedule", "client": client_name}

    try:
        resp = requests.post(GOOGLE_SHEET_WEBHOOK, json=payload, timeout=10)
        result = resp.json() if resp.ok else {"ok": False, "error": "Script error"}
    except Exception as e:
        log.error(f"[attendance_router] Failed to close reschedule: {e}")
        result = {"ok": False, "error": str(e)}

    if result.get("ok"):
        send_whatsapp_template(
            to=NADINE_WA,
            name=TPL_ADMIN_ALERT,
            lang=TEMPLATE_LANG,
            variables=[f"✅ Closed reschedule for {client_name}"],
        )

    return jsonify(result)


# ─────────────────────────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────────────────────────
@bp.route("/attendance", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "Attendance Router"}), 200
