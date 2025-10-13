#render_backend/app/package_events.py
"""
package_events.py
────────────────────────────────────────────
Handles package-related updates from Google Sheets.

Endpoints:
 • POST /package-events
   → Handles low-balance alerts, renewals, or admin summaries.

Expected payload examples:
{
  "type": "client-generic-alert",
  "message": "Hi Mary, only 2 sessions left in your pack. Renew soon!",
  "wa_number": "27735534607"
}
"""

from __future__ import annotations
import logging
from flask import Blueprint, request, jsonify
from datetime import datetime
from . import utils
from .utils import safe_execute

bp = Blueprint("package_events", __name__)
log = logging.getLogger(__name__)

TEMPLATE_GENERIC = "client_generic_alert_us"
TEMPLATE_ADMIN = "admin_generic_alert_us"
TEMPLATE_LANG = "en_US"


def _send_generic_alert(to: str, msg: str) -> bool:
    """Send a WhatsApp alert using a generic client template."""
    return safe_execute(
        f"send_package_alert to {to}",
        utils.send_whatsapp_template,
        to,
        TEMPLATE_GENERIC,
        TEMPLATE_LANG,
        [str(msg or "").strip()],
    )


@bp.route("/package-events", methods=["POST"])
def handle_package_events():
    """Receive package events (low balance, renewals, or admin summaries)."""
    payload = request.get_json(force=True)
    event_type = (payload.get("type") or "").strip()
    log.info(f"[package-events] Received type={event_type}")

    if event_type == "client-generic-alert":
        msg = payload.get("message", "")
        wa_number = payload.get("wa_number", "")
        ok = _send_generic_alert(wa_number, msg)
        return jsonify({"ok": ok, "message": msg})

    elif event_type == "admin-generic-alert":
        msg = payload.get("message", "")
        from os import getenv
        NADINE_WA = getenv("NADINE_WA", "")
        if NADINE_WA:
            safe_execute(
                "send_admin_package_alert",
                utils.send_whatsapp_template,
                NADINE_WA,
                TEMPLATE_ADMIN,
                TEMPLATE_LANG,
                [str(msg or "").strip()],
            )
            log.info(f"[package-events] Admin alert sent to Nadine: {msg}")
        return jsonify({"ok": True, "message": msg})

    log.warning(f"[package-events] Unknown type: {event_type}")
    return jsonify({"ok": False, "error": f"Unknown type: {event_type}"}), 400


@bp.route("/package-events/test", methods=["GET"])
def test_package_events():
    """Simple health check endpoint."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return jsonify({"ok": True, "timestamp": now, "route": "package-events"})
