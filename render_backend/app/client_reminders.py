#app/client_reminders.py
"""
client_reminders.py
────────────────────────────────────────────
Handles reminder jobs sent from Google Apps Script.

Supports both:
 • Job-based reminders (night-before, week-ahead, next-hour)
 • Direct single reminders from Apps Script payloads

Includes:
 - Normalisation of session_type ("reformer single" → "single")
 - Safe fallback to admin alert if unrecognised
────────────────────────────────────────────
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
# Constants (template names)
# ──────────────────────────────────────────────
TPL_NIGHT = "client_session_tomorrow_us"
TPL_WEEK = "client_weekly_schedule_us"
TPL_NEXT_HOUR = "client_session_next_hour_us"
TPL_SINGLE = "client_single_reminder_us"
TPL_DUO = "client_duo_reminder_us"
TPL_TRIO = "client_trio_reminder_us"
TEMPLATE_LANG = "en_US"


# ──────────────────────────────────────────────
# Helper
# ──────────────────────────────────────────────
def _send_template(to: str, tpl: str, vars: dict):
    """Send a WhatsApp template message safely."""
    return safe_execute(
        f"send_template {tpl}",
        utils.send_whatsapp_template,
        to,
        tpl,
        TEMPLATE_LANG,
        [str(v or "").strip() for v in vars.values()],
    )


# ──────────────────────────────────────────────
# POST endpoint from Apps Script
# ──────────────────────────────────────────────
@bp.route("/client-reminders", methods=["POST"])
def handle_client_reminders():
    """
    Receives either:
    • Job-style payloads from Apps Script (type + sessions list)
    • Direct single-session payloads from Apps Script (wa_number + session_type + date)
    """
    payload = request.get_json(force=True)
    log.info(f"[Tasks] /client-reminders payload: {payload}")

    # ──────────────────────────────────────────────
    # Direct single-session payload (from Apps Script)
    # ──────────────────────────────────────────────
    if "wa_number" in payload:
        wa_number = str(payload.get("wa_number"))
        client_name = payload.get("client_name", "there")

        # Prefer explicit session_type over type
        session_type_raw = payload.get("session_type")
        type_fallback = payload.get("type")

        # Decide final string to check
        stype_raw = (session_type_raw or type_fallback or "").lower().strip()

        # If both exist and differ, ignore "type"
        if session_type_raw and type_fallback and session_type_raw.lower() != type_fallback.lower():
            log.info(f"Ignoring fallback type '{type_fallback}' because session_type='{session_type_raw}'")

        session_date = payload.get("date") or payload.get("session_date")
        session_time = payload.get("start_time", "08:00")

        # Normalise known phrases
        if "single" in stype_raw:
            session_type = "single"
            tpl = TPL_SINGLE
        elif "duo" in stype_raw:
            session_type = "duo"
            tpl = TPL_DUO
        elif "trio" in stype_raw:
            session_type = "trio"
            tpl = TPL_TRIO
        else:
            # Unknown → notify admin for investigation
            combined = f"{session_type_raw} / {type_fallback}"
            admin_wa = payload.get("admin_number")
            warn_msg = f"⚠️ Unknown client reminder type: {combined}"
            log.warning(warn_msg)
            if admin_wa:
                _send_template(admin_wa, "admin_generic_alert_us", {"1": warn_msg})
            return jsonify({"ok": True, "note": "Unknown session_type"}), 200

        # Build template variables
        vars = {"1": client_name, "2": session_date, "3": session_time}

        ok = _send_template(wa_number, tpl, vars)
        if ok:
            log.info(f"✅ Sent {session_type} reminder → {wa_number}")
            return jsonify({"ok": True, "template": tpl, "to": wa_number}), 200
        else:
            log.error(f"❌ Failed to send {session_type} reminder → {wa_number}")
            return jsonify({"ok": False, "error": "Failed to send"}), 500

    # ──────────────────────────────────────────────
    # Job-type payloads (night-before, week-ahead, next-hour)
    # ──────────────────────────────────────────────
    job_type = (payload.get("type") or "").strip()
    sessions = payload.get("sessions", [])
    log.info(f"[client-reminders] Received job={job_type}, count={len(sessions)}")

    sent = 0

    if job_type == "client-night-before":
        for s in sessions:
            ok = _send_template(
                s.get("wa_number"),
                TPL_NIGHT,
                {"1": s.get("session_time", "")},
            )
            sent += 1 if ok else 0

    elif job_type == "client-week-ahead":
        for s in sessions:
            msg = f"{s.get('session_date')} – {s.get('session_time')} ({s.get('session_type')})"
            ok = _send_template(
                s.get("wa_number"),
                TPL_WEEK,
                {"1": s.get("client_name", 'there'), "2": msg},
            )
            sent += 1 if ok else 0

    elif job_type == "client-next-hour":
        for s in sessions:
            ok = _send_template(
                s.get("wa_number"),
                TPL_NEXT_HOUR,
                {"1": s.get("session_time", "")},
            )
            sent += 1 if ok else 0

    else:
        return jsonify({"ok": False, "error": f"Unknown job type: {job_type}"}), 400

    log.info(f"[client-reminders] Job={job_type} → Sent={sent}")
    return jsonify({"ok": True, "sent": sent})


# ──────────────────────────────────────────────
# Health check
# ──────────────────────────────────────────────
@bp.route("/client-reminders/test", methods=["GET"])
def test_route():
    """Simple health check."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log.info(f"[client-reminders] Test route hit at {now}")
    return jsonify({"ok": True, "timestamp": now})
