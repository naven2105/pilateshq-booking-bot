# app/client_behaviour.py
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
from flask import Blueprint, request, jsonify
from .utils import send_whatsapp_template, safe_execute
from .config import NADINE_WA, TEMPLATE_LANG

bp = Blueprint("client_behaviour", __name__)
log = logging.getLogger(__name__)

# Approved Meta template names
ADMIN_TEMPLATE = "admin_generic_alert_us"
CLIENT_TEMPLATE = "client_generic_alert_us"


@bp.route("/client-behaviour", methods=["POST"])
def handle_client_behaviour():
    """Receive attendance analytics payload from Google Apps Script."""
    try:
        payload = request.get_json(force=True) or {}
        inactive = payload.get("inactive", [])
        repeat_no_shows = payload.get("no_shows", [])
        repeat_cancels = payload.get("cancellations", [])

        log.info(
            f"[client_behaviour] Received: "
            f"{len(inactive)} inactive, {len(repeat_no_shows)} no-shows, {len(repeat_cancels)} cancels"
        )

        # ── 1️⃣ Build summary for Nadine ───────────────────────────────
        summary_lines = []
        if repeat_no_shows:
            summary_lines.append("🚫 *Frequent No-Shows:*\n• " + "\n• ".join(repeat_no_shows))
        if repeat_cancels:
            summary_lines.append("↩️ *Frequent Cancellations:*\n• " + "\n• ".join(repeat_cancels))
        if inactive:
            summary_lines.append("💤 *Inactive Clients (>30 days):*\n• " + "\n• ".join(inactive))

        if summary_lines:
            summary_msg = "📋 *PilatesHQ Attendance Insights*\n\n" + "\n\n".join(summary_lines)
            safe_execute(
                send_whatsapp_template,
                NADINE_WA,
                ADMIN_TEMPLATE,
                TEMPLATE_LANG,
                [summary_msg],
                label="admin_behaviour_summary",
            )
        else:
            log.info("[client_behaviour] No alerts to send — all clients active.")

        # ── 2️⃣ Optional: Reactivation message to inactive clients ─────
        for entry in inactive:
            # Expect format like "Mary Smith (27735534607)"
            parts = entry.split("(")
            name = parts[0].strip()
            wa = parts[1].replace(")", "").strip() if len(parts) > 1 else None
            if not wa:
                continue

            msg = f"Hi {name}, we miss you at PilatesHQ! 💜 Would you like to book a session this week?"
            safe_execute(
                send_whatsapp_template,
                wa,
                CLIENT_TEMPLATE,
                TEMPLATE_LANG,
                [msg],
                label="client_reactivation",
            )

        return jsonify({"ok": True, "inactive": len(inactive)}), 200

    except Exception as e:
        log.exception("❌ Error in handle_client_behaviour")
        return jsonify({"ok": False, "error": str(e)}), 500
