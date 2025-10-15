# app/attendance_router.py
"""
attendance_router.py
────────────────────────────────────────────
Handles client attendance actions such as reschedule.
Records into Google Sheets via Apps Script with timestamp, date/time, and status.
────────────────────────────────────────────
"""

import os
import pytz
import logging
import requests
import datetime
from flask import Blueprint, request, jsonify
from .utils import send_whatsapp_template

bp = Blueprint("attendance_bp", __name__)
log = logging.getLogger(__name__)

# ── Environment ──────────────────────────────────────────────────────────
GOOGLE_SHEET_WEBHOOK = os.getenv("GOOGLE_SHEET_WEBHOOK")
CLIENT_SHEET_ID = os.getenv("CLIENT_SHEET_ID")
NADINE_WA = os.getenv("NADINE_WA", "")
TEMPLATE_LANG = os.getenv("TEMPLATE_LANG", "en_US")
TZ_NAME = os.getenv("TZ_NAME", "Africa/Johannesburg")

TPL_CLIENT_ALERT = "client_generic_alert_us"
TPL_ADMIN_ALERT = "admin_generic_alert_us"


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
def _now_local() -> str:
    tz = pytz.timezone(TZ_NAME)
    return datetime.datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")


def _notify_client(wa_number: str, client_name: str):
    send_whatsapp_template(
        to=wa_number,
        name=TPL_CLIENT_ALERT,
        lang=TEMPLATE_LANG,
        variables=[
            f"Hi {client_name}, we’ve received your reschedule request. Nadine will confirm a new time soon."
        ],
    )


def _notify_admin(client_name: str, date: str, time: str, message: str):
    if not NADINE_WA:
        log.warning("⚠️ NADINE_WA not configured.")
        return

    alert = f"Reschedule Request: {client_name} — {date} {time}. Msg: {message}"
    send_whatsapp_template(
        to=NADINE_WA,
        name=TPL_ADMIN_ALERT,
        lang=TEMPLATE_LANG,
        variables=[alert],
    )


def _append_to_sheet(client_name: str, wa_number: str, date: str, time: str, message: str):
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
        resp = requests.post(GOOGLE_SHEET_WEBHOOK, json=payload, timeout=30)
        log.info(f"[attendance_router] Sheet append → {resp.status_code} | {resp.text}")
    except Exception as e:
        log.error(f"[attendance_router] Failed to append to Google Sheet: {e}")


# ─────────────────────────────────────────────────────────────
# ROUTE: /attendance/log
# ─────────────────────────────────────────────────────────────
@bp.route("/attendance/log", methods=["POST"])
def log_attendance():
    data = request.get_json(force=True)
    log.info(f"[attendance_router] Incoming payload: {data}")

    wa_number = data.get("from") or data.get("wa_number")
    client_name = data.get("name") or data.get("client_name") or "Unknown"
    message = (data.get("message") or "").strip()

    if not wa_number or not client_name:
        return jsonify({"ok": False, "error": "Missing required fields"}), 400

    if "reschedule" not in message.lower():
        return jsonify({"ok": False, "reason": "no reschedule keyword found"}), 400

    date_guess, time_guess = "", ""
    for token in message.split():
        if ":" in token or ("h" in token and token.lower().replace("h", "").isdigit()):
            time_guess = token.replace("h", ":")
        if any(d in token.lower() for d in ["mon", "tue", "wed", "thu", "fri", "sat", "sun", "day"]):
            date_guess = token

    _append_to_sheet(client_name, wa_number, date_guess, time_guess, message)
    _notify_client(wa_number, client_name)
    _notify_admin(client_name, date_guess or "-", time_guess or "-", message)

    return jsonify({"ok": True, "action": "reschedule"})


# ─────────────────────────────────────────────────────────────
# ROUTE: /attendance/close
# ─────────────────────────────────────────────────────────────
@bp.route("/attendance/close", methods=["POST"])
def close_reschedule():
    data = request.get_json(force=True)
    client_name = data.get("client_name")

    if not client_name:
        return jsonify({"ok": False, "error": "Missing client name"}), 400

    payload = {"action": "close_reschedule", "client": client_name, "sheet_id": CLIENT_SHEET_ID}
    try:
        resp = requests.post(GOOGLE_SHEET_WEBHOOK, json=payload, timeout=30)
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


@bp.route("/attendance", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "Attendance Router"}), 200
