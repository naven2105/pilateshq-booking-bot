"""
tasks_router.py – Phase 18 (Unified Version)
────────────────────────────────────────────
Purpose:
 • Central webhook handler for all time-based automation triggers.
 • Google Apps Script (GAS) is responsible for scheduling triggers
   and calling these endpoints on Render.

Includes:
 • /tasks/run-reminders → Admin morning/evening/week summary
 • /tasks/client-reminders → Client session templates
 • /tasks/package-events → Admin package alerts
 • /tasks/client-behaviour → Behaviour analytics
 • /tasks/birthdays + /tasks/birthday-greetings → Birthday automation

Merged:
 • Integrated client_reminders.py logic (next-hour, night-before, week-ahead)
────────────────────────────────────────────
"""

import os
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify
from .utils import send_safe_message, safe_execute, send_whatsapp_template

# ─────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────
log = logging.getLogger(__name__)
tasks_bp = Blueprint("tasks_bp", __name__)

# Environment
NADINE_WA = os.getenv("NADINE_WA", "")
TEMPLATE_LANG = os.getenv("TEMPLATE_LANG", "en_US")

# Templates
TPL_ADMIN_ALERT = "admin_generic_alert_us"
TPL_CLIENT_NEXT_HOUR = "client_session_next_hour_us"
TPL_CLIENT_TOMORROW = "client_session_tomorrow_us"
TPL_CLIENT_WEEKLY = "client_weekly_schedule_us"

# ─────────────────────────────────────────────
# Helper: Send admin template safely
# ─────────────────────────────────────────────
def _send_admin_message(msg: str, label="admin_alert"):
    """Send WhatsApp alert to Nadine safely using admin template."""
    if not NADINE_WA:
        log.warning("⚠️ NADINE_WA not configured.")
        return
    safe_execute(
        label,
        send_whatsapp_template,
        NADINE_WA,
        TPL_ADMIN_ALERT,
        TEMPLATE_LANG,
        [msg],
    )
    log.info(f"📲 Admin alert sent: {msg}")


# ─────────────────────────────────────────────
# ROUTE: Admin morning/evening/week-ahead summaries
# ─────────────────────────────────────────────
@tasks_bp.route("/run-reminders", methods=["POST"])
def run_reminders():
    """
    Triggered by GAS (06h00, 20h00, Sunday night).
    Sends admin summary based on schedule data.
    """
    data = request.get_json(force=True)
    log.info(f"[Tasks] /run-reminders payload: {data}")

    msg_type = data.get("type", "")
    total = data.get("total", 0)
    schedule = data.get("schedule", "No sessions")

    if msg_type == "morning":
        msg = f"🌅 PilatesHQ Morning Summary: {total} sessions today. Schedule: {schedule}"
    elif msg_type == "evening":
        msg = f"🌙 PilatesHQ Evening Preview: {total} sessions tomorrow. Schedule: {schedule}."
    elif msg_type == "week_ahead_admin":
        msg = f"📆 PilatesHQ Week-Ahead Preview: {total} sessions scheduled. Schedule: {schedule}"
    else:
        msg = f"🕐 Unknown reminder type received ({msg_type})."

    _send_admin_message(msg, label=f"run_reminders_{msg_type}")
    return jsonify({"ok": True, "message": msg})


# ─────────────────────────────────────────────
# ROUTE: Unified client reminder handler
# ─────────────────────────────────────────────
@tasks_bp.route("/client-reminders", methods=["POST"])
def handle_client_reminders():
    """
    Handles all client engagement templates triggered by GAS:
      - client-night-before   (20h00 daily)
      - client-week-ahead     (Sunday 20h00)
      - client-next-hour      (hourly)
    """
    payload = request.get_json(force=True)
    job_type = (payload.get("type") or "").strip()
    sessions = payload.get("sessions", [])
    admin_number = payload.get("admin_number", NADINE_WA)
    log.info(f"[client-reminders] Received job={job_type}, count={len(sessions)}")

    sent_clients = 0

    # Night-before (20h00)
    if job_type == "client-night-before":
        for s in sessions:
            wa = s.get("wa_number")
            if not wa:
                continue
            ok = safe_execute(
                "night_before",
                send_whatsapp_template,
                wa,
                TPL_CLIENT_TOMORROW,
                TEMPLATE_LANG,
                [s.get("session_time", "08:00")],
            )
            if ok:
                sent_clients += 1
        _send_admin_message(f"🌙 Sent night-before reminders ({sent_clients}).")

    # Week-ahead (Sunday 20h00)
    elif job_type == "client-week-ahead":
        for s in sessions:
            wa = s.get("wa_number")
            if not wa:
                continue
            summary = f"{s.get('session_date')} – {s.get('session_time')} ({s.get('session_type')})"
            ok = safe_execute(
                "week_ahead",
                send_whatsapp_template,
                wa,
                TPL_CLIENT_WEEKLY,
                TEMPLATE_LANG,
                [s.get("client_name", "there"), summary],
            )
            if ok:
                sent_clients += 1
        _send_admin_message(f"📅 Sent week-ahead reminders ({sent_clients}).")

    # Next-hour reminders (hourly)
    elif job_type == "client-next-hour":
        for s in sessions:
            wa = s.get("wa_number")
            if not wa:
                continue
            ok = safe_execute(
                "next_hour",
                send_whatsapp_template,
                wa,
                TPL_CLIENT_NEXT_HOUR,
                TEMPLATE_LANG,
                [s.get("session_time", "soon")],
            )
            if ok:
                sent_clients += 1
        _send_admin_message(f"⏰ Sent next-hour reminders ({sent_clients}).")

    # Fallback for unknown type
    else:
        _send_admin_message(f"⚠️ Unknown reminder type: {job_type}")
        return jsonify({"ok": False, "error": f"Unknown job type: {job_type}"}), 400

    log.info(f"[client-reminders] Job={job_type} → Sent={sent_clients}")
    return jsonify({"ok": True, "sent_clients": sent_clients, "message": job_type})


# ─────────────────────────────────────────────
# ROUTE: Test route for health checks
# ─────────────────────────────────────────────
@tasks_bp.route("/client-reminders/test", methods=["GET"])
def test_client_reminders():
    """Simple test endpoint to confirm route is alive."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return jsonify({"ok": True, "timestamp": now})


# ─────────────────────────────────────────────
# ROUTE: Admin package / credits events
# ─────────────────────────────────────────────
@tasks_bp.route("/package-events", methods=["POST"])
def package_events():
    """Sends admin alerts for package or credit events."""
    data = request.get_json(force=True)
    log.info(f"[Tasks] /package-events payload: {data}")
    message = data.get("message", "No message")
    _send_admin_message(message, label="package_event")
    return jsonify({"ok": True, "message": "Sent to Nadine"})


# ─────────────────────────────────────────────
# ROUTE: Client behaviour analytics (weekly)
# ─────────────────────────────────────────────
@tasks_bp.route("/client-behaviour", methods=["POST"])
def client_behaviour():
    """Handles weekly analytics of client behaviour."""
    data = request.get_json(force=True)
    log.info(f"[Tasks] /client-behaviour payload: {data}")

    no_shows = data.get("no_shows", [])
    cancels = data.get("cancellations", [])
    inactive = data.get("inactive", [])

    summary = (
        f"📊 Client Behaviour Summary\n"
        f"❌ No-shows: {len(no_shows)}\n"
        f"↩️ Cancellations: {len(cancels)}\n"
        f"💤 Inactive: {len(inactive)}"
    )
    _send_admin_message(summary, label="client_behaviour_summary")
    return jsonify({"ok": True, "message": summary})


# ─────────────────────────────────────────────
# ROUTE: Birthday reminders + greetings
# ─────────────────────────────────────────────
@tasks_bp.route("/birthdays", methods=["POST"])
def birthdays():
    """Sends admin alert for upcoming birthdays."""
    data = request.get_json(force=True)
    log.info(f"[Tasks] /birthdays payload: {data}")

    birthdays = data.get("birthdays", [])
    if not birthdays:
        return jsonify({"ok": True, "message": "No upcoming birthdays"})

    names = ", ".join([f"{b['name']} ({b['date']})" for b in birthdays])
    msg = f"🎉 PilatesHQ Birthday Planner: {names}"
    _send_admin_message(msg, label="birthday_alert")
    return jsonify({"ok": True, "message": msg})


@tasks_bp.route("/birthday-greetings", methods=["POST"])
def birthday_greetings():
    """Sends personalised birthday greetings to clients."""
    data = request.get_json(force=True)
    log.info(f"[Tasks] /birthday-greetings payload: {data}")

    birthdays = data.get("birthdays", [])
    if not birthdays:
        return jsonify({"ok": True, "message": "No client birthdays today"})

    for b in birthdays:
        name = b.get("name")
        wa = b.get("wa_number")
        if not wa:
            continue

        send_safe_message(
            to=wa,
            is_template=True,
            template_name="client_generic_alert_us",
            variables=[f"🎉 Happy Birthday {name}! Wishing you strength and balance for the year ahead."],
            label="client_birthday_greeting",
        )
        log.info(f"🎂 Sent birthday greeting to {name} ({wa})")

    names = ", ".join([b["name"] for b in birthdays])
    admin_msg = f"🎂 PilatesHQ Birthday Greetings sent to: {names}"
    _send_admin_message(admin_msg, label="birthday_greetings_summary")

    return jsonify({"ok": True, "sent": len(birthdays), "message": admin_msg})
