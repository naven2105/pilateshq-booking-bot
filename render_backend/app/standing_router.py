# app/standing_router.py
"""
standing_router.py – Phase 30 (Specials-Aware Standing Booking)
───────────────────────────────────────────────────────────────
Purpose:
  Handles recurring client slots (“book”, “suspend”, “resume”) and forwards to Apps Script.
  Adds optional SPECIAL_CODE parsing (e.g., BF2025) and forwards it as 'special_code'
  while preserving the original text for GAS-side parsing.

Admin examples (WhatsApp → Nadine only):
  - "book Terrance Tuesday 09h00 group BF2025"
  - "book Mary 2025-11-12 07h00 single"
  - "book John every Wednesday 08h00 duo BF2025"
  - "suspend Mary"
  - "resume Mary"

Forwards requests to Google Apps Script → handleStandingCommand(payload)
Payload shape:
  {
    "from": "<admin_wa>",
    "text": "<original admin text>",
    "special_code": "<OPTIONAL e.g. BF2025>"
  }
───────────────────────────────────────────────────────────────
"""

from flask import Blueprint, request, jsonify
import requests
import os
import logging
import re

log = logging.getLogger(__name__)
bp = Blueprint("standing_router", __name__)

# Environment variable (your Apps Script deployment URL)
GAS_STANDING_URL = os.getenv(
    "GAS_STANDING_URL",
    "https://script.google.com/macros/s/AKfycbwYOUR_DEPLOYMENT_ID/exec"
)

# Nadine’s number (from env or fallback)
ADMIN_WA = os.getenv("ADMIN_WA", "27627597357")

# Simple SPECIAL_CODE pattern: letters/digits/underscore, e.g. BF2025
SPECIAL_CODE_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9_]{2,})\b")


def _extract_special_code(cmd: str) -> str | None:
    """
    Heuristic:
      - Look at the final token; if it looks like a promo code (BF2025, SUMMER24),
        treat it as special_code.
      - We do NOT remove it from text; GAS will also parse the full text.
    """
    if not cmd:
        return None
    parts = cmd.strip().split()
    if len(parts) < 2:
        return None
    candidate = parts[-1].strip()
    # Avoid common non-codes that appear at the end
    if candidate.lower() in {"single", "duo", "group", "resume", "suspend", "book", "every"}:
        return None
    # Accept codes like BF2025, SUMMER_2026, etc.
    if SPECIAL_CODE_RE.fullmatch(candidate):
        return candidate
    return None


@bp.route("/standing/command", methods=["POST"])
def standing_command():
    """Receive WhatsApp messages for standing slot actions."""
    try:
        data = request.get_json(force=True) or {}
        wa_from = str(data.get("from", "")).strip()
        text = (data.get("text") or "").strip()

        if not text:
            return jsonify({"ok": False, "error": "Empty message"}), 400

        # Only allow admin (Nadine)
        if wa_from != ADMIN_WA:
            log.warning(f"Unauthorized standing command from {wa_from}")
            return jsonify({"ok": False, "error": "Unauthorized"}), 403

        special_code = _extract_special_code(text)
        if special_code:
            log.info(f"[standing] Parsed special_code={special_code} from: {text}")

        # Forward to Google Apps Script
        payload = {"from": wa_from, "text": text}
        if special_code:
            payload["special_code"] = special_code

        log.info(f"[standing] → GAS_STANDING_URL POST: {payload}")
        res = requests.post(GAS_STANDING_URL, json=payload, timeout=15)
        js = res.json() if res.text else {"ok": False, "error": "No response body"}

        log.info(f"[standing] GAS response: HTTP {res.status_code} {js}")
        return jsonify(js), (res.status_code if res.status_code else 200)

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
