# render_backend/app/tasks_reminders.py
"""
tasks_reminders.py
────────────────────────────────────────────
Receives scheduled trigger requests from Google Apps Script.
Sends admin reminders via WhatsApp templates.
"""

import os
from flask import Blueprint, request, jsonify
from render_backend.app.utils import send_whatsapp_template

tasks_bp = Blueprint("tasks_bp", __name__)

NADINE_WA = os.getenv("NADINE_WA", "")
TEMPLATE_LANG = os.getenv("TEMPLATE_LANG", "en_US")

TPL_ADMIN_MORNING = "tpl_admin_morning"
TPL_ADMIN_20H00 = "tpl_admin_20h00"


@tasks_bp.route("/tasks/run-reminders", methods=["POST"])
def run_reminders():
    """Triggered by Google Apps Script for daily reminders."""
    data = request.get_json(force=True)
    reminder_type = (data or {}).get("type", "evening").lower()

    if not NADINE_WA:
        return jsonify({"error": "NADINE_WA not configured"}), 400

    print(f"📅 Reminder trigger received: {reminder_type}")

    # Determine template to send
    if reminder_type in ["morning", "am"]:
        template_name = TPL_ADMIN_MORNING
    else:
        template_name = TPL_ADMIN_20H00

    result = send_whatsapp_template(
        to=NADINE_WA,
        name=template_name,
        lang=TEMPLATE_LANG,
        variables=[]
    )

    if result.get("ok"):
        print(f"✅ Reminder sent successfully → {template_name}")
        return jsonify({"status": "sent", "template": template_name}), 200

    print(f"❌ Failed to send reminder → {result}")
    return jsonify({"error": "failed to send", "details": result}), 500
