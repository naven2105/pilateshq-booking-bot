"""
schedule_router.py – Phase 16 (Booking & Reminder Automation)
────────────────────────────────────────────────────────────
Handles studio schedule functions for PilatesHQ.

Key Features
 • /schedule/add-session     → Add booked session to Google Sheet
 • /schedule/reschedule      → Mark session as rescheduled
 • /schedule/admin-morning   → Morning summary (06h00)
 • /schedule/admin-evening   → Next-day preview (20h00)
 • /schedule/health          → Service check

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
GAS_SCHEDULE_URL = os.getenv("GAS_SCHEDULE_URL", "")
NADINE_WA = os.getenv("NADINE_WA", "")
TPL_ADMIN = "admin_generic_alert_us"

# ─────────────────────────────────────────────────────────────
# Internal helper for posting to GAS
# ─────────────────────────────────────────────────────────────
def _post_to_gas(payload: dict):
    if not GAS_SCHEDULE_URL:
        return {"ok": False, "error": "Missing GAS_SCHEDULE_URL"}
    try:
        r = requests.post(GAS_SCHEDULE_URL, json=payload, timeout=20)
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
        session_type = data.get("session_type", "").strip()
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
                to=NADINE_WA,
                is_template=True,
                template_name=TPL_ADMIN,
                variables=[f"⚠️ Failed to add session for {client_name}: {resp.get('error')}"],
                label="add_session_error"
            )
            return jsonify(resp), 502

        send_safe_message(
            to=NADINE_WA,
            is_template=True,
            template_name=TPL_ADMIN,
            variables=[f"✅ Added session: {client_name} – {session_day} {session_time} ({session_type})"],
            label="add_session_ok"
        )
        return jsonify({"ok": True, "message": "Session added", "gas_result": resp}), 200

    except Exception as e:
        log.exception("add_session error")
        return jsonify({"ok": False, "error": str(e)}), 500

# ─────────────────────────────────────────────────────────────
#  /schedule/mark-reschedule
#  Triggered when Nadine (or NLP) requests "reschedule {client_name}"
#  Sends action to Google Apps Script → marks session as rescheduled
#  Designed to handle both human (Nadine) and NLP requests uniformly
# ─────────────────────────────────────────────────────────────
@bp.route("/schedule/mark-reschedule", methods=["POST"])
def mark_reschedule():
    try:
        # ── 1️⃣ Validate Input ───────────────────────────────────────
        data = request.get_json(force=True)
        client_name = (data.get("client_name") or "").strip()

        if not client_name:
            log.warning("mark_reschedule() called with missing client_name")
            return jsonify({"ok": False, "error": "Missing client_name"}), 400

        log.info(f"Reschedule request received for client: {client_name}")

        # ── 2️⃣ Prepare GAS Payload ─────────────────────────────────
        payload = {"action": "mark_reschedule", "client_name": client_name}
        gas_url = os.getenv("GAS_ATTENDANCE_URL", "")

        if not gas_url:
            err_msg = "Missing GAS_ATTENDANCE_URL in environment"
            log.error(err_msg)
            send_safe_message(NADINE_WA, f"⚠ System setup issue: {err_msg}")
            return jsonify({"ok": False, "error": err_msg}), 500

        # ── 3️⃣ Call GAS Endpoint ───────────────────────────────────
        log.debug(f"Calling GAS URL: {gas_url} → {payload}")
        resp = requests.post(gas_url, json=payload, timeout=20)
        gas_text = resp.text.strip()
        gas_result = resp.json() if gas_text else {}

        log.debug(f"GAS response: {gas_result}")

        # ── 4️⃣ Interpret GAS Response ───────────────────────────────
        if gas_result.get("ok"):
            msg = f"✅ Session updated: {client_name} marked as rescheduled."
            log.info(msg)
            send_safe_message(NADINE_WA, msg)
            return jsonify({
                "ok": True,
                "message": "Session rescheduled",
                "gas_result": gas_result,
            })

        # Handle failure response from GAS
        error_msg = gas_result.get("error") or gas_result.get("message") or "Unknown error"
        log.warning(f"Reschedule failed for {client_name}: {error_msg}")
        send_safe_message(
            NADINE_WA,
            f"⚠ Unable to mark session for {client_name}: {error_msg}"
        )
        return jsonify({"ok": False, "error": error_msg}), 502

    # ── 5️⃣ Handle Exceptions ───────────────────────────────────────
    except requests.exceptions.Timeout:
        log.error("GAS request timed out")
        send_safe_message(NADINE_WA, f"⚠ GAS request timeout for {client_name}")
        return jsonify({"ok": False, "error": "GAS request timeout"}), 504

    except Exception as e:
        log.exception(f"mark_reschedule() failed: {e}")
        send_safe_message(
            NADINE_WA,
            f"⚠ System error while rescheduling {client_name}: {str(e)}"
        )
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# 2️⃣ Reschedule Session
# ─────────────────────────────────────────────────────────────
@bp.route("/reschedule", methods=["POST"])
def mark_reschedule():
    """Mark client session as rescheduled."""
    try:
        data = request.get_json(force=True)
        client_name = data.get("client_name", "").strip()

        if not client_name:
            return jsonify({"ok": False, "error": "Missing client_name"}), 400

        resp = _post_to_gas({"action": "mark_reschedule", "client_name": client_name})
        msg = "Reschedule marked" if resp.get("ok") else f"Error: {resp.get('error')}"
        send_safe_message(
            to=NADINE_WA,
            is_template=True,
            template_name=TPL_ADMIN,
            variables=[f"🔁 {client_name} rescheduled – {msg}"],
            label="reschedule_notice"
        )
        return jsonify(resp), (200 if resp.get("ok") else 502)
    except Exception as e:
        log.exception("reschedule error")
        return jsonify({"ok": False, "error": str(e)}), 500

# ─────────────────────────────────────────────────────────────
# 3️⃣ Morning & Evening Admin Digests
# ─────────────────────────────────────────────────────────────
@bp.route("/admin-morning", methods=["POST"])
def admin_morning():
    """Called by GAS 06h00 → summary of today's sessions."""
    try:
        payload = {"action": "get_sessions_today"}
        resp = _post_to_gas(payload)
        if not resp.get("ok"):
            raise ValueError(resp.get("error"))
        summary = resp.get("summary", "No sessions today.")
        send_safe_message(
            to=NADINE_WA,
            is_template=True,
            template_name=TPL_ADMIN,
            variables=[f"🌅 Today’s sessions: {summary}"],
            label="admin_morning"
        )
        return jsonify(resp)
    except Exception as e:
        log.error(f"admin_morning error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

@bp.route("/admin-evening", methods=["POST"])
def admin_evening():
    """Called by GAS 20h00 → preview tomorrow’s sessions."""
    try:
        payload = {"action": "get_sessions_tomorrow"}
        resp = _post_to_gas(payload)
        if not resp.get("ok"):
            raise ValueError(resp.get("error"))
        summary = resp.get("summary", "No sessions tomorrow.")
        send_safe_message(
            to=NADINE_WA,
            is_template=True,
            template_name=TPL_ADMIN,
            variables=[f"🌙 Tomorrow’s sessions: {summary}"],
            label="admin_evening"
        )
        return jsonify(resp)
    except Exception as e:
        log.error(f"admin_evening error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

# ─────────────────────────────────────────────────────────────
# 0️⃣ Unified Dispatcher (for external POST calls)
# ─────────────────────────────────────────────────────────────
@bp.route("/", methods=["POST"])
def schedule_dispatch():
    """Generic schedule entrypoint for external callers (e.g. Render test)."""
    try:
        data = request.get_json(force=True)
        action = (data.get("action") or "").strip()

        # Match supported actions
        if action == "add_session":
            return add_session()
        elif action == "mark_reschedule":
            return mark_reschedule()
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
# 4️⃣ Health
# ─────────────────────────────────────────────────────────────
@bp.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "Schedule Router",
        "endpoints": [
            "/schedule/add-session",
            "/schedule/reschedule",
            "/schedule/admin-morning",
            "/schedule/admin-evening",
            "/schedule/health"
        ]
    }), 200
