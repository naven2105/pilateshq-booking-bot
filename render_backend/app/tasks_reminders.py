# render_backend/app/tasks_reminders.py
"""
tasks_reminders.py
────────────────────────────────────────────
Receives scheduled trigger requests from Google Apps Script.
Sends admin reminders via WhatsApp templates with live data.
"""

import os
from flask import Blueprint, request, jsonify
from render_backend.app.utils import send_whatsapp_template

tasks_bp = Blueprint("tasks_bp", __name__)

# ── Environment Variables ─────────────────────────────────────────────
NADINE_WA = os.getenv("NADINE_WA", "")
TEMPLATE_LANG = os.getenv("TEMPLATE_LANG", "en_US")

# ── Meta Template Names ───────────────────────────────────────────────
TPL_ADMIN_MORNING = "admin_morning_us"
TPL_ADMIN_20H00 = "admin_20h00_us"


@tasks_bp.route("/tasks/run-reminders", methods=["POST"])
def run_reminders():
    """
    Triggered by Google Apps Script for daily reminders.
    Expected payload:
    {
      "type": "morning",
      "sessions": 5,
      "times": "07h00 – Lisa / 08h00 – Tom / 17h30 – Jerry (rescheduled)"
    }
    """
    data = request.get_json(force=True)
    reminder_type = (data or {}).get("type", "evening").lower()
    sessions = str((data or {}).get("sessions", "0"))
    times = (data or {}).get("times", "No sessions")

    if not NADINE_WA:
        return jsonify({"ok": False, "error": "NADINE_WA not configured"}), 400

    print(f"📅 Reminder trigger received: {reminder_type}")
    print(f"   → sessions={sessions}, times={times}")

    # Determine which template to use
    if reminder_type in ["morning", "am"]:
        template_name = TPL_ADMIN_MORNING
        variables = [f"{sessions} sessions", times]
        friendly_label = "Morning Brief"
    else:
        template_name = TPL_ADMIN_20H00
        variables = [f"{sessions} sessions tomorrow", times]
        friendly_label = "Evening Preview"

    # Send WhatsApp Template
    result = send_whatsapp_template(
        to=NADINE_WA,
        name=template_name,
        lang=TEMPLATE_LANG,
        variables=variables,
    )

    # Logging and clean return
    if result.get("ok"):
        log_msg = f"✅ {friendly_label} sent successfully → {template_name}"
        print(log_msg)
        return jsonify({
            "ok": True,
            "template": template_name,
            "label": friendly_label,
            "variables": variables,
            "status_code": result.get("status_code", 200)
        }), 200

    print(f"❌ Failed to send {friendly_label} → {result}")
    return jsonify({
        "ok": False,
        "error": "failed to send",
        "label": friendly_label,
        "details": result
    }), 500
