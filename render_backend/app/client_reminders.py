# render_backend_app/client_reminders.py
"""
client_reminders.py – Final Stable Version
────────────────────────────────────────────
Handles reminder jobs sent from Google Apps Script.
Covers both single reminder POSTs and batch reminder jobs.
Automatically normalises 'reformer single' → 'single' etc.
"""

from __future__ import annotations
import logging
from flask import Blueprint, request, jsonify
from datetime import datetime
from . import utils
from .utils import safe_execute

bp = Blueprint("client_reminders", __name__)
log = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Template Names
# ──────────────────────────────────────────────
TPL_SINGLE = "client_single_reminder_us"
TPL_DUO = "client_duo_reminder_us"
TPL_TRIO = "client_trio_reminder_us"
TPL_NIGHT = "client_session_tomorrow_us"
TPL_WEEK = "client_weekly_schedule_us"
TPL_NEXT_HOUR = "client_session_next_hour_us"
TEMPLATE_LANG = "en_US"


# ──────────────────────────────────────────────
# Safe Template Sender
# ──────────────────────────────────────────────
def _send_template(to: str, tpl: str, vars: dict):
    """Send a WhatsApp template safely and log the call."""
    return safe_execute(
        f"send_template {tpl}",
        utils.send_whatsapp_template,
        to,
        tpl,
        TEMPLATE_LANG,
        [str(v or "").strip() for v in vars.values()],
    )


# ──────────────────────────────────────────────
# Primary Route: Handles single or batch reminders
# ──────────────────────────────────────────────
@bp.route("/client-reminders", methods=["POST"])
def handle_client_reminders():
    payload = request.get_json(force=True)
    log.info(f"[Tasks] /client-reminders payload: {payload}")

    # ───── Single reminder (Apps Script direct call) ─────
    if "wa_number" in payload:
        wa = str(payload.get("wa_number"))
        name = payload.get("client_name", "there")
        date = payload.get("date") or payload.get("session_date")
        time = payload.get("start_time", "08:00")

        # Prefer explicit session_type, normalise reformer terms
        stype_raw = (payload.get("session_type") or payload.get("type") or "").lower().strip()
        if "reformer" in stype_raw:
            stype_raw = stype_raw.replace("reformer", "").strip()

        log.info(f"[Reminder] Normalised session_type='{stype_raw}'")

        # Select template based on type
        tpl = None
        if "single" in stype_raw:
            tpl = TPL_SINGLE
        elif "duo" in stype_raw:
            tpl = TPL_DUO
        elif "trio" in stype_raw:
            tpl = TPL_TRIO

        if tpl:
            ok = _send_template(wa, tpl, {"1": name, "2": date, "3": time})
            if ok:
                log.info(f"✅ Sent {stype_raw} reminder to {wa}")
                return jsonify({"ok": True, "type": stype_raw}), 200
            else:
                log.error(f"❌ Failed to send {stype_raw} reminder to {wa}")
                return jsonify({"ok": False, "error": "send failed"}), 500

        # Unknown → alert admin
        warn_msg = f"⚠️ Unknown client reminder type: {stype_raw}"
        log.warning(warn_msg)
        admin_wa = payload.get("admin_number")
        if admin_wa:
            _send_template(admin_wa, "admin_generic_alert_us", {"1": warn_msg})
        return jsonify({"ok": True, "note": "Unknown type"}), 200

    # ───── Batch jobs (weekly, next-hour, etc.) ─────
    job_type = (payload.get("type") or "").strip()
    sessions = payload.get("sessions", [])
    sent = 0

    if job_type == "client-night-before":
        for s in sessions:
            ok = _send_template(s.get("wa_number"), TPL_NIGHT, {"1": s.get("session_time", "")})
            sent += 1 if ok else 0

    elif job_type == "client-week-ahead":
        for s in sessions:
            msg = f"{s.get('session_date')} – {s.get('session_time')} ({s.get('session_type')})"
            ok = _send_template(s.get("wa_number"), TPL_WEEK, {"1": s.get("client_name", 'there'), "2": msg})
            sent += 1 if ok else 0

    elif job_type == "client-next-hour":
        for s in sessions:
            ok = _send_template(s.get("wa_number"), TPL_NEXT_HOUR, {"1": s.get("session_time", "")})
            sent += 1 if ok else 0

    else:
        return jsonify({"ok": False, "error": f"Unknown job type: {job_type}"}), 400

    log.info(f"[client-reminders] Job={job_type} → Sent={sent}")
    return jsonify({"ok": True, "sent": sent})


# ──────────────────────────────────────────────
# Diagnostic Route (Optional)
# ──────────────────────────────────────────────
@bp.route("/client-reminders/debug", methods=["POST"])
def debug_reminder_payload():
    payload = request.get_json(force=True)
    stype_raw = (payload.get("session_type") or payload.get("type") or "").lower().strip()
    if "reformer" in stype_raw:
        stype_raw = stype_raw.replace("reformer", "").strip()
    log.info(f"[DEBUG] Raw session_type={payload.get('session_type')} | type={payload.get('type')} | normalised={stype_raw}")
    return jsonify({
        "session_type": payload.get("session_type"),
        "type": payload.get("type"),
        "normalised": stype_raw
    })


# ──────────────────────────────────────────────
# Health Check
# ──────────────────────────────────────────────
@bp.route("/client-reminders/test", methods=["GET"])
def test_route():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return jsonify({"ok": True, "timestamp": now})
