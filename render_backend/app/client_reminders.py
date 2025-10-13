#render_backend_app/client_reminders.py
"""
client_reminders.py
────────────────────────────────────────────
Handles reminder jobs sent from Google Apps Script.
No database required.

Jobs supported:
 • client-night-before  (daily 20h00)
 • client-week-ahead    (Sunday 20h00)
 • client-next-hour     (hourly)

Each job includes a JSON list of sessions/clients.
Dispatches WhatsApp templates via utils.send_whatsapp_template.
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
TEMPLATE_LANG = "en_US"


# ──────────────────────────────────────────────
# Helper
# ──────────────────────────────────────────────
def _send_template(to: str, tpl: str, vars: dict):
    """Send a WhatsApp template message."""
    try:
        resp = utils.send_whatsapp_template(
            to=to,
            name=tpl,
            lang=TEMPLATE_LANG,
            variables=[str(v or "").strip() for v in vars.values()],
        )
        ok = resp.get("ok", False)
        log.info(f"[send_template] tpl={tpl} to={to} ok={ok}")
        return ok
    except Exception as e:
        log.warning(f"[send_template] failed for {to}: {e}")
        return False


# ──────────────────────────────────────────────
# POST endpoint from Apps Script
# ──────────────────────────────────────────────
@bp.route("/client-reminders", methods=["POST"])
@safe_execute()
def handle_client_reminders():
    """
    Payload examples:
    {
      "type": "client-night-before",
      "sessions": [{"client_name": "Mary", "wa_number": "2773...", "session_time": "08:00"}]
    }

    {
      "type": "client-week-ahead",
      "sessions": [{"client_name": "Mary", "wa_number": "2773...", "session_date": "Mon 07 Oct", "session_time": "08:00", "session_type": "duo"}]
    }

    {
      "type": "client-next-hour",
      "sessions": [{"client_name": "Mary", "wa_number": "2773...", "session_time": "09:00"}]
    }
    """
    payload = request.get_json(force=True)
    job_type = (payload.get("type") or "").strip()
    sessions = payload.get("sessions", [])
    log.info(f"[client-reminders] Received job={job_type}, count={len(sessions)}")

    sent = 0

    if job_type == "client-night-before":
        for s in sessions:
            ok = _send_template(
                s.get("wa_number"),
                TPL_NIGHT,
                {"1": s.get("session_time", "")}
            )
            sent += 1 if ok else 0

    elif job_type == "client-week-ahead":
        for s in sessions:
            msg = f"{s.get('session_date')} – {s.get('session_time')} ({s.get('session_type')})"
            ok = _send_template(
                s.get("wa_number"),
                TPL_WEEK,
                {"1": s.get("client_name", 'there'), "2": msg}
            )
            sent += 1 if ok else 0

    elif job_type == "client-next-hour":
        for s in sessions:
            ok = _send_template(
                s.get("wa_number"),
                TPL_NEXT_HOUR,
                {"1": s.get("session_time", "")}
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
