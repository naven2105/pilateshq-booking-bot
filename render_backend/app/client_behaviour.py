#render_backend_app/client_behaviour.py
"""
client_behaviour.py
────────────────────────────────────────────
Weekly attendance analytics and proactive engagement.
Detects:
 - Repeated no-shows
 - Frequent cancellations
 - Inactive clients (>30 days without attendance)

Sends:
 - Admin summary (to Nadine)
 - Reactivation message to inactive clients
"""

import logging
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify
from .utils import send_whatsapp_template

bp = Blueprint("client_behaviour", __name__)
log = logging.getLogger(__name__)

TEMPLATE_ADMIN = "admin_generic_alert_us"
TEMPLATE_CLIENT = "client_generic_alert_us"


@bp.route("/client-behaviour", methods=["POST"])
def handle_client_behaviour():
    """Receive attendance payload from Apps Script and send alerts."""
    try:
        payload = request.get_json(force=True)
        inactive = payload.get("inactive", [])
        repeat_no_shows = payload.get("no_shows", [])
        repeat_cancels = payload.get("cancellations", [])

        log.info(f"[client-behaviour] Received: {len(inactive)} inactive, "
                 f"{len(repeat_no_shows)} no-shows, {len(repeat_cancels)} cancellations")

        # 1️⃣ Admin Summary Message
        summary_lines = []
        if repeat_no_shows:
            summary_lines.append("🚫 Frequent No-Shows:\n• " + "\n• ".join(repeat_no_shows))
        if repeat_cancels:
            summary_lines.append("↩️ Frequent Cancellations:\n• " + "\n• ".join(repeat_cancels))
        if inactive:
            summary_lines.append("💤 Inactive Clients (>30 days):\n• " + "\n• ".join(inactive))

        summary_msg = "📋 PilatesHQ Attendance Insights\n\n" + "\n\n".join(summary_lines or ["✅ All clients active."])

        send_whatsapp_template(
            to="277xxxxxxx",  # ⚙️ replace with Nadine's WA (or env var)
            name=TEMPLATE_ADMIN,
            lang="en_US",
            variables=[summary_msg]
        )

        # 2️⃣ Send reactivation message to inactive clients
        for client in inactive:
            parts = client.split("(")
            name = parts[0].strip()
            number = parts[1].replace(")", "").strip() if len(parts) > 1 else None
            if number:
                send_whatsapp_template(
                    to=number,
                    name=TEMPLATE_CLIENT,
                    lang="en_US",
                    variables=[f"{name}, we miss you at PilatesHQ! Would you like to book a session this week?"]
                )

        return jsonify({"ok": True, "inactive": len(inactive)}), 200

    except Exception as e:
        log.exception("❌ Error in handle_client_behaviour")
        return jsonify({"ok": False, "error": str(e)}), 500
