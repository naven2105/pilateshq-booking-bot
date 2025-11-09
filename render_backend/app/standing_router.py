# app/standing_router.py
"""
standing_router.py – Phase 30B (Specials + Action Routing)
──────────────────────────────────────────────────────────────
Purpose:
  Handles recurring client slot commands (“book”, “suspend”, “resume”)
  and forwards them to Google Apps Script.

Enhancements:
  • Adds optional SPECIAL_CODE parsing (e.g. BF2025)
  • Adds explicit "action": "standing_command" so GAS knows how to route
  • Returns clean JSON with GAS feedback or error
──────────────────────────────────────────────────────────────
"""

from flask import Blueprint, request, jsonify
import requests
import os
import logging
import re

log = logging.getLogger(__name__)
bp = Blueprint("standing_router", __name__)

# ───────────────────────────────────────────────
# Environment variables
# ───────────────────────────────────────────────
GAS_STANDING_URL = os.getenv(
    "GAS_STANDING_URL",
    "https://script.google.com/macros/s/AKfycbx-009V1LZWXldZMF4gWhXM07z681FYIhJiT0biOM3fXZvteDhe8Jhynls88TYuVU6jpw/exec"
)
ADMIN_WA = os.getenv("ADMIN_WA", "27627597357")

# Code pattern: letters/digits/underscore, e.g. BF2025, SUMMER_24
SPECIAL_CODE_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9_]{2,})\b")


# ───────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────
def _extract_special_code(cmd: str) -> str | None:
    """
    Detects if the final token looks like a promotion code.
    Returns None if not present.
    """
    if not cmd:
        return None
    parts = cmd.strip().split()
    if len(parts) < 2:
        return None
    candidate = parts[-1].strip()
    if candidate.lower() in {"single", "duo", "group", "resume", "suspend", "book", "every"}:
        return None
    if SPECIAL_CODE_RE.fullmatch(candidate):
        return candidate
    return None


# ───────────────────────────────────────────────
# Main route
# ───────────────────────────────────────────────
@bp.route("/standing/command", methods=["POST"])
def standing_command():
    """Receive WhatsApp messages for standing slot actions."""
    try:
        data = request.get_json(force=True) or {}
        wa_from = str(data.get("from", "")).strip()
        text = (data.get("text") or "").strip()

        if not text:
            return jsonify({"ok": False, "error": "Empty message"}), 400

        # Restrict to admin
        if wa_from != ADMIN_WA:
            log.warning(f"Unauthorized standing command from {wa_from}")
            return jsonify({"ok": False, "error": "Unauthorized"}), 403

        # Parse optional special code
        special_code = _extract_special_code(text)
        if special_code:
            log.info(f"[standing] Parsed special_code={special_code} from: {text}")

        # Build payload for GAS
        payload = {
            "action": "standing_command",   # 👈 key addition
            "from": wa_from,
            "text": text
        }
        if special_code:
            payload["special_code"] = special_code

        log.info(f"[standing→GAS] POST {GAS_STANDING_URL} payload={payload}")
        res = requests.post(GAS_STANDING_URL, json=payload, timeout=15)

        if res.status_code == 404:
            log.error(f"GAS returned 404 — likely old deployment or missing case in doPost")
        js = res.json() if res.text else {"ok": False, "error": f"HTTP {res.status_code}"}

        log.info(f"[standing] GAS response: {js}")
        return jsonify(js), res.status_code

    except Exception as e:
        log.exception("standing_command error")
        return jsonify({"ok": False, "error": str(e)}), 500


# ───────────────────────────────────────────────
# Blueprint registration
# ───────────────────────────────────────────────
def register_standing_routes(app):
    """Attach the standing_router blueprint to Flask app."""
    app.register_blueprint(bp, url_prefix="/tasks")
    log.info("standing_router registered at /tasks/standing/command")
