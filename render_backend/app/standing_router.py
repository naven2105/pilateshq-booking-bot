# app/standing_router.py
"""
standing_router.py – Phase 30C (Fixed GAS Action + Specials)
──────────────────────────────────────────────────────────────
Purpose:
  Handles recurring client slot commands (“book”, “suspend”, “resume”)
  and forwards them to Google Apps Script (GAS).

Enhancements:
  • Explicitly sets "action": "standing_command" so GAS router recognises it
  • Optional parsing of promotion codes (e.g. BF2025)
  • Clear JSON feedback + structured logging
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
    "https://script.google.com/macros/s/AKfycbzhZgscmpyCTN3xOJJvP3Ey-nVxmQvQo8ZHZEAptARX1ickJbieHfrFyhy_B9pMF_m73A/exec"
)
ADMIN_WA = os.getenv("ADMIN_WA", "27627597357")

# Detect codes like BF2025 or SUMMER_24 at end of command
SPECIAL_CODE_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9_]{2,})\b")

# ───────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────
def _extract_special_code(cmd: str) -> str | None:
    """Detect promotion/special code token at the end of message."""
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
# Route handler
# ───────────────────────────────────────────────
@bp.route("/standing/command", methods=["POST"])
def standing_command():
    """Handles admin WhatsApp booking/suspend/resume commands."""
    try:
        data = request.get_json(force=True) or {}
        wa_from = str(data.get("from", "")).strip()
        text = (data.get("text") or "").strip()

        if not text:
            return jsonify({"ok": False, "error": "Empty message"}), 400

        # Restrict access
        if wa_from != ADMIN_WA:
            log.warning(f"Unauthorized standing command from {wa_from}")
            return jsonify({"ok": False, "error": "Unauthorized"}), 403

        # Detect optional promo/special code
        special_code = _extract_special_code(text)
        if special_code:
            log.info(f"[standing] Found special_code={special_code}")

        # Build payload for GAS router
        payload = {
            "action": "standing_command",
            "from": wa_from,
            "text": text
        }
        if special_code:
            payload["special_code"] = special_code

        log.info(f"[standing→GAS] POST {GAS_STANDING_URL} payload={payload}")
        res = requests.post(GAS_STANDING_URL, json=payload, timeout=20)

        # Parse response safely
        try:
            js = res.json() if res.text else {}
        except Exception:
            js = {"ok": False, "error": f"Non-JSON response (HTTP {res.status_code})"}

        if res.status_code == 404:
            log.error(f"GAS returned 404 — check deployment or router case mismatch")

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
