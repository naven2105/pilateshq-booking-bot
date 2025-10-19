"""
tasks_router.py
────────────────────────────────────────────
Handles task webhook calls from Google Apps Script.
────────────────────────────────────────────
"""

import os
import logging
from flask import Blueprint, request, jsonify
from .utils import send_safe_message

log = logging.getLogger(__name__)
tasks_bp = Blueprint("tasks_bp", __name__)

NADINE_WA = os.getenv("NADINE_WA", "")
TEMPLATE_LANG = os.getenv("TEMPLATE_LANG", "en_US")
TPL_ADMIN_ALERT = "admin_generic_alert_us"
TPL_CLIENT_REMINDER = "client_generic_alert_us"


# ─────────────────────────────────────────────────────────────
# Helper: send admin message safely
# ─────────────────────────────────────────────────────────────
def _send_admin_message(msg: str, label="admin_alert"):
    if not NADINE_WA:
        log.warning("⚠️ NADINE_WA not configured.")
        return
    send_safe_message(
        to=NADINE_WA,
        is_template=True,
        template_name=TPL_ADMIN_ALERT,
        variables=[msg],
        label=label
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
        msg = f"🌅 PilatesHQ Morning Summary: {total} sessions today. Schedule: {schedule}"
    elif msg_type == "evening":
        msg = f"🌙 PilatesHQ Evening Preview: {total} sessions tomorrow. Schedule: {schedule}. Sleep well! 💤"
    else:
        msg = f"🕐 Unknown reminder type received ({msg_type})."

    _send_admin_message(msg, label=f"run_reminders_{msg_type}")
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

        send_safe_message(
            to=wa,
            is_template=True,
            template_name=TPL_CLIENT_REMINDER,
            variables=[f"Hi {name}, this is a friendly reminder for your class at {time}. See you soon! 💪"],
            label="client_next_hour"
        )

    _send_admin_message(f"⏰ Sent {len(clients)} next-hour client reminders.", label="client_next_hour_summary")
    return jsonify({"ok": True, "count": len(clients)})


# ─────────────────────────────────────────────────────────────
# ROUTE: Package events (credits, low-balance, etc.)
# ─────────────────────────────────────────────────────────────
@tasks_bp.route("/package-events", methods=["POST"])
def package_events():
    data = request.get_json(force=True)
    log.info(f"[Tasks] /package-events payload: {data}")

    message = data.get("message", "No message")
    _send_admin_message(message, label="package_event")
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

