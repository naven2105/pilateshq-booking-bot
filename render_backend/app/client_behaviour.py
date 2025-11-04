"""
client_behaviour.py – Phase 21 (Analytics + Health)
────────────────────────────────────────────────────────────
Weekly attendance analytics and proactive engagement.
────────────────────────────────────────────────────────────
"""

import logging
from flask import Blueprint, request, jsonify
from .utils import send_whatsapp_template, safe_execute
from .config import NADINE_WA, TEMPLATE_LANG

bp = Blueprint("client_behaviour", __name__)
log = logging.getLogger(__name__)

ADMIN_TEMPLATE = "admin_generic_alert_us"
CLIENT_TEMPLATE = "client_generic_alert_us"

@bp.route("/client-behaviour", methods=["POST"])
def handle_client_behaviour():
    """Receive analytics payload from GAS."""
    try:
        payload = request.get_json(force=True) or {}
        inactive = payload.get("inactive", [])
        repeat_no_shows = payload.get("no_shows", [])
        repeat_cancels = payload.get("cancellations", [])

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
                label="admin_behaviour_summary"
            )

        return jsonify({"ok": True, "inactive": len(inactive)}), 200
    except Exception as e:
        log.exception("❌ handle_client_behaviour error")
        return jsonify({"ok": False, "error": str(e)}), 500

# ─────────────────────────────────────────────────────────────
# Health routes
# ─────────────────────────────────────────────────────────────
@bp.route("/health", methods=["GET"])
@bp.route("/", methods=["GET"])
def health_behaviour():
    """Simple blueprint health check."""
    return jsonify({
        "status": "ok",
        "service": "client_behaviour"
    }), 200
