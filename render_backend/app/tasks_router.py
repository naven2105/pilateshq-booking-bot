# render_backend/app/tasks_router.py
"""
tasks_router.py
────────────────────────────────────────────
Handles task webhook calls from Google Apps Script.
Routes:
 - /tasks/run-reminders          → Admin morning/evening summaries
 - /tasks/client-next-hour       → Client next-hour reminders
 - /tasks/client-reminders       → Client night-before / week-ahead
 - /tasks/package-events         → Package low-balance, unused credits
 - /tasks/client-behaviour       → Weekly attendance analytics
────────────────────────────────────────────
"""

import os
import logging
from flask import Blueprint, request, jsonify
from render_backend.app.utils import send_whatsapp_template

# ── Setup ──────────────────────────────────────────────────────
log = logging.getLogger(__name__)
tasks_bp = Blueprint("tasks_bp", __name__)

NADINE_WA = os.getenv("NADINE_WA", "")
TEMPLATE_LANG = os.getenv("TEMPLATE_LANG", "en_US")

# Templates used across events
TPL_ADMIN_ALERT = "admin_generic_alert_us"
TPL_CLIENT_REMINDER = "client_generic_alert_us"


# ─────────────────────────────────────────────────────────────
# Helper: send message safely
# ─────────────────────────────────────────────────────────────
def _send_admin_message(msg: str):
    """Send a WhatsApp message to Nadine."""
    if not NADINE_WA:
        log.warning("⚠️ NADINE_WA not configured.")
        return
    send_whatsapp_template(
        to=NADINE_WA,
        name=TPL_ADMIN_ALERT,
        lang=TEMPLATE_LANG,
        variables=[msg],
    )
    log.info(f"📲 Sent admin WhatsApp alert → {msg}")


# ─────────────────────────────────────────────────────────────
# ROUTE: Admin morning/evening reminders
# ─────────────────────────────────────────────────────────────
@tasks_bp.route("/run-reminders", methods=["POST"])
def run_reminders():
    data = request.get_json(force=True)
    log.info(f"[Tasks] /run-reminders payload: {data}")

    msg_type = data.get("type")
    total = data.get("total", 0)
    schedule = data.get("schedule", "No sessions")

    if msg_type == "morning":
        msg = f"🌅 Morning job ran successfully.\nSessions today: {total}\nSchedule: {schedule}"
    elif msg_type == "evening":
        msg = f"🌙 Evening preview – Tomorrow has {total} sessions booked.\nSchedule: {schedule}\nSleep well! 💤"
    else:
        msg = f"🕐 Unknown reminder type received ({msg_type})."

    _send_admin_message(msg)
    return jsonify({"ok": True, "message": msg})


# ─────────────────────────────────────────────────────────────
# ROUTE: Client next-hour reminders
# ─────────────────────────────────────────────────────────────
@tasks_bp.route("/client-next-hour", methods=["POST"])
def client_next_hour():
    data = request.get_json(force=True)
    log.info(f"[Tasks] /client-next-hour payload: {data}")

    clients = data.get("clients", [])
    if not clients:
        return jsonify({"ok": True, "message": "No clients for next hour."})

    for c in clients:
        wa = c.get("wa_number")
        name = c.get("name")
        time = c.get("time")
        if not wa:
            continue

        send_whatsapp_template(
            to=wa,
            name=TPL_CLIENT_REMINDER,
            lang=TEMPLATE_LANG,
            variables=[f"Hi {name}, this is a friendly reminder for your class at {time}. See you soon! 💪"],
        )

    _send_admin_message(f"⏰ Sent {len(clients)} next-hour client reminders.")
    return jsonify({"ok": True, "count": len(clients)})


# ─────────────────────────────────────────────────────────────
# ROUTE: Client night-before / week-ahead reminders
# ─────────────────────────────────────────────────────────────
@tasks_bp.route("/client-reminders", methods=["POST"])
def client_reminders():
    data = request.get_json(force=True)
    log.info(f"[Tasks] /client-reminders payload: {data}")

    msg_type = data.get("type")

    if msg_type == "client-night-before":
        _send_admin_message("🌙 Sent client night-before reminders.")
    elif msg_type == "client-week-ahead":
        _send_admin_message("📅 Sent client week-ahead summaries.")
    else:
        _send_admin_message(f"⚠️ Unknown client reminder type: {msg_type}")

    return jsonify({"ok": True, "message": msg_type})


# ─────────────────────────────────────────────────────────────
# ROUTE: Package events (credits, low-balance, reschedule)
# ─────────────────────────────────────────────────────────────
@tasks_bp.route("/package-events", methods=["POST"])
def package_events():
    data = request.get_json(force=True)
    log.info(f"[Tasks] /package-events payload: {data}")

    message = data.get("message", "No message")
    _send_admin_message(message)

    return jsonify({"ok": True, "message": "Sent to Nadine"})


# ─────────────────────────────────────────────────────────────
# ROUTE: Client behaviour analytics (weekly)
# ─────────────────────────────────────────────────────────────
@tasks_bp.route("/client-behaviour", methods=["POST"])
def client_behaviour():
    data = request.get_json(force=True)
    log.info(f"[Tasks] /client-behaviour payload: {data}")

    no_shows = data.get("no_shows", [])
    cancels = data.get("cancellations", [])
    inactive = data.get("inactive", [])

    summary = (
        "📊 Client Behaviour Summary (last 30 days):\n"
        f"• No-shows (2+): {len(no_shows)}\n"
        f"• Frequent cancellations (3+): {len(cancels)}\n"
        f"• Inactive (>30 days): {len(inactive)}"
    )

    _send_admin_message(summary)
    return jsonify({"ok": True, "summary": summary})


# ─────────────────────────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────────────────────────
@tasks_bp.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "PilatesHQ Tasks Router"}), 200
