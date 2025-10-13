"""
client_reminders.py
────────────────────────────────────────────
Handles reminder jobs sent from Google Apps Script.

Jobs supported:
 • client-night-before  (daily 20h00)
 • client-week-ahead    (Sunday 20h00)
 • client-next-hour     (hourly)

Now supports both:
 • Client-facing WhatsApp templates
 • Admin confirmation messages
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
# WhatsApp Templates
# ──────────────────────────────────────────────
TPL_NIGHT = "client_session_tomorrow_us"      # Client: Night-before
TPL_WEEK = "client_weekly_schedule_us"        # Client: Week ahead
TPL_NEXT_HOUR = "client_session_next_hour_us" # Client: Next-hour
TPL_ADMIN = "admin_generic_alert_us"          # Admin: Summary
TEMPLATE_LANG = "en_US"


# ──────────────────────────────────────────────
# Helper wrappers
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


def _notify_admin(admin_number: str, text: str):
    """Send admin confirmation summary."""
    if not admin_number:
        return
    _send_template(admin_number, TPL_ADMIN, {"1": text})


# ──────────────────────────────────────────────
# POST endpoint from Apps Script
# ──────────────────────────────────────────────
@bp.route("/client-reminders", methods=["POST"])
def handle_client_reminders():
    """
    Receives payloads like:
    { "type": "client-night-before", "sessions": [...] }
    """
    payload = request.get_json(force=True)
    job_type = (payload.get("type") or "").strip()
    sessions = payload.get("sessions", [])
    admin_number = payload.get("admin_number")
    log.info(f"[client-reminders] Received job={job_type}, count={len(sessions)}")

    sent_clients = 0

    # ─── CLIENT NIGHT-BEFORE ─────────────────────────────
    if job_type == "client-night-before":
        for s in sessions:
            ok = _send_template(
                s.get("wa_number"),
                TPL_NIGHT,
                {"1": s.get("session_time", "08:00")},
            )
            sent_clients += 1 if ok else 0
        _notify_admin(admin_number, f"🌙 Sent client night-before reminders ({sent_clients}).")

    # ─── CLIENT WEEK-AHEAD ───────────────────────────────
    elif job_type == "client-week-ahead":
        for s in sessions:
            msg = f"{s.get('session_date')} – {s.get('session_time')} ({s.get('session_type')})"
            ok = _send_template(
                s.get("wa_number"),
                TPL_WEEK,
                {"1": s.get("client_name", 'there'), "2": msg},
            )
            sent_clients += 1 if ok else 0
        _notify_admin(admin_number, f"📅 Sent client week-ahead reminders ({sent_clients}).")

    # ─── CLIENT NEXT-HOUR ────────────────────────────────
    elif job_type == "client-next-hour":
        for s in sessions:
            ok = _send_template(
                s.get("wa_number"),
                TPL_NEXT_HOUR,
                {"1": s.get("session_time", "")},
            )
            sent_clients += 1 if ok else 0
        _notify_admin(admin_number, f"⏰ Sent client next-hour reminders ({sent_clients}).")

    else:
        _notify_admin(admin_number, f"⚠️ Unknown client reminder type: {job_type}")
        return jsonify({"ok": False, "error": f"Unknown job type: {job_type}"}), 400

    log.info(f"[client-reminders] Job={job_type} → Sent={sent_clients}")
    return jsonify({"ok": True, "sent_clients": sent_clients, "message": job_type})


# ──────────────────────────────────────────────
# Health check
# ──────────────────────────────────────────────
@bp.route("/client-reminders/test", methods=["GET"])
def test_route():
    """Simple health check."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log.info(f"[client-reminders] Test route hit at {now}")
    return jsonify({"ok": True, "timestamp": now})
