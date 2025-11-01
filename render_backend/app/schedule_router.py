"""
schedule_router.py – Phase 25A (Reschedule + No-Show Integration)
────────────────────────────────────────────────────────────
Handles studio schedule functions for PilatesHQ.

✅ Enhancements
 • Supports `type` field (reschedule / noshow)
 • Unified handling for Nadine & client actions
 • Logs success / failure to WhatsApp
 • Retains all admin morning & evening digests

All actual trigger timings are run in Google Apps Script; this backend
just exposes callable endpoints for GAS or Nadine’s WhatsApp commands.
────────────────────────────────────────────────────────────
"""

import os, logging, requests
from flask import Blueprint, request, jsonify
from datetime import datetime
from .utils import send_safe_message

bp = Blueprint("schedule_bp", __name__)
log = logging.getLogger(__name__)

# ── Environment ─────────────────────────────────────────────
GAS_SCHEDULE_URL   = os.getenv("GAS_SCHEDULE_URL", "")
GAS_ATTENDANCE_URL = os.getenv("GAS_ATTENDANCE_URL", "")
NADINE_WA          = os.getenv("NADINE_WA", "")
TPL_ADMIN          = "admin_generic_alert_us"


# ─────────────────────────────────────────────────────────────
# Helper: post to GAS with safety
# ─────────────────────────────────────────────────────────────
def _post_to_gas(payload: dict):
    url = GAS_ATTENDANCE_URL or GAS_SCHEDULE_URL
    if not url:
        return {"ok": False, "error": "Missing GAS_ATTENDANCE_URL or GAS_SCHEDULE_URL"}
    try:
        r = requests.post(url, json=payload, timeout=20)
        return r.json() if r.ok else {"ok": False, "error": f"GAS HTTP {r.status_code}"}
    except Exception as e:
        log.error(f"GAS POST failed: {e}")
        return {"ok": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────
# 1️⃣ Add Session
# ─────────────────────────────────────────────────────────────
@bp.route("/add-session", methods=["POST"])
def add_session():
    """Add a booked client session to the Sessions Sheet."""
    try:
        data = request.get_json(force=True)
        client_name = data.get("client_name", "").strip()
        session_day = data.get("day", "").strip()
        session_time = data.get("time", "").strip()
        session_type = data.get("session_type", "").strip() or "Group"
        week = data.get("week", "").strip() or "Current"

        if not client_name or not session_day or not session_time:
            return jsonify({"ok": False, "error": "Missing required fields"}), 400

        payload = {
            "action": "add_session",
            "client_name": client_name,
            "day": session_day,
            "time": session_time,
            "session_type": session_type,
            "week": week
        }
        resp = _post_to_gas(payload)

        if not resp.get("ok"):
            send_safe_message(
                NADINE_WA,
                f"⚠️ Failed to add session for {client_name}: {resp.get('error')}"
            )
            return jsonify(resp), 502

        send_safe_message(NADINE_WA, f"✅ Added session: {client_name} – {session_day} {session_time} ({session_type})")
        return jsonify({"ok": True, "message": "Session added", "gas_result": resp}), 200

    except Exception as e:
        log.exception("add_session error")
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# 2️⃣ Mark Reschedule / No-Show
# ─────────────────────────────────────────────────────────────
@bp.route("/schedule/mark-reschedule", methods=["POST"], endpoint="mark_reschedule_api")
def mark_reschedule_api():
    """Handles both reschedule + no-show updates coming from the webhook."""
    try:
        data = request.get_json(force=True)
        client_name = (data.get("client_name") or "").strip()
        action_type = (data.get("type") or "reschedule").strip().lower()

        if not client_name:
            return jsonify({"ok": False, "error": "Missing client_name"}), 400

        payload = {
            "action": "mark_reschedule",
            "client_name": client_name,
            "type": action_type,
            "source": data.get("source", "admin")
        }
        log.info(f"📤 Forwarding {action_type} → GAS: {payload}")

        resp = _post_to_gas(payload)

        if resp.get("ok"):
            msg = f"✅ {action_type.capitalize()} logged for {client_name}"
            log.info(msg)
            send_safe_message(NADINE_WA, msg)
            return jsonify({"ok": True, "message": msg, "gas_result": resp}), 200

        error_msg = resp.get("error", "Unknown error")
        log.warning(f"⚠️ Failed to update {client_name}: {error_msg}")
        send_safe_message(NADINE_WA, f"⚠️ Could not update {client_name}: {error_msg}")
        return jsonify({"ok": False, "error": error_msg}), 502

    except Exception as e:
        log.exception("mark_reschedule_api error")
        send_safe_message(NADINE_WA, f"⚠️ Error while updating schedule: {str(e)}")
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# 3️⃣ Morning & Evening Admin Digests
# ─────────────────────────────────────────────────────────────
@bp.route("/admin-morning", methods=["POST"])
def admin_morning():
    """Called by GAS 06h00 → summary of today's sessions."""
    try:
        resp = _post_to_gas({"action": "get_sessions_today"})
        if not resp.get("ok"):
            raise ValueError(resp.get("error"))
        summary = resp.get("summary", "No sessions today.")
        send_safe_message(NADINE_WA, f"🌅 Today’s sessions: {summary}")
        return jsonify(resp)
    except Exception as e:
        log.error(f"admin_morning error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/admin-evening", methods=["POST"])
def admin_evening():
    """Called by GAS 20h00 → preview tomorrow’s sessions."""
    try:
        resp = _post_to_gas({"action": "get_sessions_tomorrow"})
        if not resp.get("ok"):
            raise ValueError(resp.get("error"))
        summary = resp.get("summary", "No sessions tomorrow.")
        send_safe_message(NADINE_WA, f"🌙 Tomorrow’s sessions: {summary}")
        return jsonify(resp)
    except Exception as e:
        log.error(f"admin_evening error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# 4️⃣ Unified Dispatcher (for external POST calls)
# ─────────────────────────────────────────────────────────────
@bp.route("/", methods=["POST"])
def schedule_dispatch():
    """Generic entrypoint for external calls (Render or GAS tests)."""
    try:
        data = request.get_json(force=True)
        action = (data.get("action") or "").strip()

        if action == "add_session":
            return add_session()
        elif action == "mark_reschedule":
            return mark_reschedule_api()
        elif action == "get_sessions_today":
            return admin_morning()
        elif action == "get_sessions_tomorrow":
            return admin_evening()
        else:
            return jsonify({"ok": False, "error": f"Unsupported action '{action}'"}), 400

    except Exception as e:
        log.exception("schedule_dispatch error")
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# 5️⃣ Health
# ─────────────────────────────────────────────────────────────
@bp.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "Schedule Router",
        "endpoints": [
            "/schedule/add-session",
            "/schedule/mark-reschedule",
            "/schedule/admin-morning",
            "/schedule/admin-evening",
            "/schedule/health"
        ]
    }), 200
