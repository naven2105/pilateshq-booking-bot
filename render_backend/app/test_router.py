"""
test_router.py
────────────────────────────────────────────
Temporary test routes for verifying WhatsApp
template delivery and formatting safety.

• /test/send   → Sends a WhatsApp message via client template
• /test/admin  → Sends a WhatsApp message via admin template

Uses approved templates:
  - client_generic_alert_us
  - admin_generic_alert_us
────────────────────────────────────────────
"""

import logging
from flask import Blueprint, request, jsonify
from .utils import send_safe_message
import os

bp = Blueprint("test_bp", __name__)
log = logging.getLogger(__name__)

# ── Environment ─────────────────────────────────────────────
DEFAULT_CLIENT = os.getenv("TEST_CLIENT_WA", "27735534607")
DEFAULT_ADMIN = os.getenv("NADINE_WA", "")

# ─────────────────────────────────────────────────────────────
# ROUTE: /test/send – Test client template
# ─────────────────────────────────────────────────────────────
@bp.route("/send", methods=["POST"])
def test_send_template():
    """
    Example POST body:
    {
        "to": "27735534607",
        "template_name": "client_generic_alert_us",
        "variables": [
            "📑 PilatesHQ Invoice – October 2025. "
            "02, 04, 09 Oct Duo (R250) × 3; 11, 18 Oct Single (R300) × 2. "
            "Total R1,350 | Paid R900 | Balance R450. "
            "PDF: https://drive.google.com/abcd1234"
        ]
    }
    """
    try:
        data = request.get_json(force=True)
        to = data.get("to", DEFAULT_CLIENT)
        template = data.get("template_name", "client_generic_alert_us")
        variables = data.get("variables", [])
        label = data.get("label", "test_client_send")

        log.info(f"🧪 Test send (client): template={template} to={to} vars={variables}")
        resp = send_safe_message(
            to=to,
            is_template=True,
            template_name=template,
            variables=variables,
            label=label
        )
        return jsonify({"ok": True, "response": resp}), 200

    except Exception as e:
        log.error(f"❌ test_send_template error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# ROUTE: /test/admin – Test admin template
# ─────────────────────────────────────────────────────────────
@bp.route("/admin", methods=["POST"])
def test_admin_template():
    """
    Example POST body:
    {
        "to": "27627597357",
        "variables": ["📊 PilatesHQ Weekly Revenue: R15,000. Outstanding: R2,100. Keep it up! 💪"]
    }
    """
    try:
        data = request.get_json(force=True)
        to = data.get("to", DEFAULT_ADMIN)
        variables = data.get("variables", ["📊 PilatesHQ Weekly Test Alert."])
        label = data.get("label", "test_admin_send")

        log.info(f"🧪 Test send (admin): template=admin_generic_alert_us to={to} vars={variables}")
        resp = send_safe_message(
            to=to,
            is_template=True,
            template_name="admin_generic_alert_us",
            variables=variables,
            label=label
        )
        return jsonify({"ok": True, "response": resp}), 200

    except Exception as e:
        log.error(f"❌ test_admin_template error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500
