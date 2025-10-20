"""
test_router.py
────────────────────────────────────────────
For manual developer testing of WhatsApp messaging routes.
────────────────────────────────────────────
"""

import os
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify
from .utils import send_safe_message
from .invoices import generate_invoice_whatsapp

log = logging.getLogger(__name__)
bp = Blueprint("test_bp", __name__)

# ── Environment ──────────────────────────────────────────────
NADINE_WA = os.getenv("NADINE_WA", "27627597357")
TEST_WA = os.getenv("TEST_WA", "27735534607")  # Naven test number
TPL_CLIENT_ALERT = "client_generic_alert_us"
TPL_ADMIN_ALERT = "admin_generic_alert_us"
BASE_URL = os.getenv("BASE_URL", "https://pilateshq-booking-bot.onrender.com")


# ─────────────────────────────────────────────────────────────
# /test/send → send any message using template
# ─────────────────────────────────────────────────────────────
@bp.route("/test/send", methods=["POST"])
def test_send_template():
    """Send arbitrary message via template for quick verification."""
    try:
        data = request.get_json(force=True)
        to = data.get("to", TEST_WA)
        variables = data.get("variables", ["💜 PilatesHQ test message OK."])
        template = data.get("template", TPL_CLIENT_ALERT)
        log.info(f"[test_send_template] → {to} | {variables}")
        resp = send_safe_message(
            to=to,
            is_template=True,
            template_name=template,
            variables=variables,
            label="test_send_template",
        )
        return jsonify({"ok": True, "response": resp})
    except Exception as e:
        log.error(f"❌ test_send_template error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# /test/invoice → Generate and send sample invoice (dynamic month)
# ─────────────────────────────────────────────────────────────
@bp.route("/test/invoice", methods=["POST", "GET"])
def test_invoice_send():
    """
    Generates a sample PilatesHQ invoice WhatsApp message for testing.
    Uses the current month automatically.
    """
    try:
        # Determine current month
        now = datetime.now()
        month_name = now.strftime("%B %Y")  # e.g. "October 2025"

        # Build fake data (real generator uses CRUD + DB)
        client_name = "Test Client"
        wa_number = TEST_WA
        # Generate WhatsApp-friendly text
        message = (
            f"📑 *PilatesHQ Invoice – {month_name}*\n"
            f"02, 04 {now.strftime('%b')} Duo (R250) × 2; "
            f"11, 18 {now.strftime('%b')} Single (R300) × 2.\n"
            f"💰 *Total R1,100 | Paid R600 | Balance R500*\n"
            f"📎 PDF: https://drive.google.com/abcd1234"
        )

        # Send using approved template
        resp = send_safe_message(
            to=wa_number,
            is_template=True,
            template_name=TPL_CLIENT_ALERT,
            variables=[message],
            label="test_invoice_send",
        )

        log.info(f"✅ Test invoice message sent to {wa_number}: {message}")
        return jsonify({
            "ok": True,
            "to": wa_number,
            "message": message,
            "response": resp
        })

    except Exception as e:
        log.error(f"❌ test_invoice_send error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# Health Check
# ─────────────────────────────────────────────────────────────
@bp.route("/test", methods=["GET"])
def health():
    """Simple sanity check."""
    return jsonify({
        "status": "ok",
        "service": "Test Router",
        "endpoints": ["/test/send", "/test/invoice"]
    }), 200
