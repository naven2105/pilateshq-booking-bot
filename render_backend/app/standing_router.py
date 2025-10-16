#app/standing_router.py
"""
standing_router.py
───────────────────────────────────────────────
Purpose: Handles recurring client slots (“book”, “suspend”, “resume”) and forwards to Apps Script.
Handles admin commands for recurring client slots:
 - "book Fatima Khan tuesday 08h00 group"
 - "suspend Fatima Khan"
 - "resume Fatima Khan"

Forwards requests to Google Apps Script → handleStandingCommand()
───────────────────────────────────────────────
"""

from flask import Blueprint, request, jsonify
import requests
import os
import logging

log = logging.getLogger(__name__)
bp = Blueprint("standing_router", __name__)

# Environment variable (your Apps Script deployment URL)
GAS_STANDING_URL = os.getenv(
    "GAS_STANDING_URL",
    "https://script.google.com/macros/s/AKfycbwYOUR_DEPLOYMENT_ID/exec"
)

# Nadine’s number (from env or fallback)
ADMIN_WA = os.getenv("ADMIN_WA", "27627597357")


@bp.route("/standing/command", methods=["POST"])
def standing_command():
    """Receive WhatsApp messages for standing slot actions."""
    try:
        data = request.get_json(force=True)
        wa_from = str(data.get("from", ""))
        text = (data.get("text") or "").strip()

        if not text:
            return jsonify({"ok": False, "error": "Empty message"}), 400

        # Only allow admin (Nadine)
        if wa_from != ADMIN_WA:
            log.warning(f"Unauthorized standing command from {wa_from}")
            return jsonify({"ok": False, "error": "Unauthorized"}), 403

        # Forward to Google Apps Script
        payload = {"from": wa_from, "text": text}
        res = requests.post(GAS_STANDING_URL, json=payload, timeout=10)
        js = res.json() if res.text else {}

        log.info(f"Standing command → GAS response: {js}")
        return jsonify(js)

    except Exception as e:
        log.exception("standing_command error")
        return jsonify({"ok": False, "error": str(e)}), 500


# ───────────────────────────────────────────────
# Optional: helper to register blueprint in main app
# ───────────────────────────────────────────────
def register_standing_routes(app):
    """Attach the standing_router blueprint to Flask app."""
    app.register_blueprint(bp, url_prefix="/tasks")
    log.info("standing_router registered at /tasks/standing/command")
