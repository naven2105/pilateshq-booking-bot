#render_backend/app/package_events.py
"""
app/package_events.py
────────────────────────────────────────────
Handles package-related updates from Google Sheets.

Endpoints:
 • POST /tasks/package-events
     → Low-balance alerts, renewals, or summary updates.

Expected payload examples from Apps Script:
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
from .utils import sanitize_param, safe_execute

bp = Blueprint("package_events", __name__)
log = logging.getLogger(__name__)

TEMPLATE_GENERIC = "client_generic_alert_us"
TEMPLATE_LANG = "en_US"


def _send_generic_alert(to: str, msg: str) -> bool:
    """Send a simple WhatsApp message using the generic template."""
    try:
        resp = utils.send_whatsapp_template(
            to=to,
            name=TEMPLATE_GENERIC,
            lang=TEMPLATE_LANG,
            variables=[sanitize_param(msg)],
        )
        ok = resp.get("ok", False)
        log.info(f"[package-alert] to={to} ok={ok} msg={msg}")
        return ok
    except Exception as e:
        log.warning(f"[package-alert] failed to send to {to}: {e}")
        return False


@bp.route("/package-events", methods=["POST"])
@safe_execute
def handle_package_events():
    """Receive package events (low balance, renewals, etc.) from Apps Script."""
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
            utils.send_whatsapp_template(
                to=NADINE_WA,
                name="admin_generic_alert_us",
                lang="en_US",
                variables=[sanitize_param(msg)],
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
