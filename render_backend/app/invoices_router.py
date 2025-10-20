"""
invoices_router.py – Phase 6 (Integrated Test)
────────────────────────────────────────────
Adds:
 • /invoices/unpaid      → returns all unpaid or partial invoices
 • /invoices/test-send   → sends or tests WhatsApp invoice message
────────────────────────────────────────────
"""

import os, logging, requests
from datetime import datetime
from flask import Blueprint, request, jsonify
from .utils import send_safe_message

bp = Blueprint("invoices_bp", __name__)
log = logging.getLogger(__name__)

# ── Environment ──────────────────────────────────────────────
NADINE_WA = os.getenv("NADINE_WA", "")
GAS_INVOICE_URL = os.getenv("GAS_INVOICE_URL", "")
SHEET_ID = os.getenv("CLIENT_SHEET_ID", "")
TPL_ADMIN_ALERT = "admin_generic_alert_us"
TPL_CLIENT_ALERT = "client_generic_alert_us"
BASE_URL = os.getenv("BASE_URL", "https://pilateshq-booking-bot.onrender.com")


# ─────────────────────────────────────────────────────────────
# Utility: Unified Apps Script POST
# ─────────────────────────────────────────────────────────────
def _post_to_gas(payload: dict) -> dict:
    """Safely post JSON payload to Google Apps Script endpoint."""
    try:
        if not GAS_INVOICE_URL:
            raise ValueError("Missing GAS_INVOICE_URL environment variable.")
        r = requests.post(GAS_INVOICE_URL, json=payload, timeout=15)
        if not r.ok:
            log.error(f"Apps Script HTTP {r.status_code}: {r.text}")
            return {"ok": False, "error": f"Apps Script HTTP {r.status_code}"}
        return r.json()
    except Exception as e:
        log.error(f"[invoices_router] GAS POST failed: {e}")
        return {"ok": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────
# /invoices/unpaid → Returns unpaid / partial invoices
# ─────────────────────────────────────────────────────────────
@bp.route("/unpaid", methods=["GET", "POST"])
def list_unpaid_invoices():
    """
    Returns all unpaid or partially paid invoices from Google Apps Script.
    POST also triggers WhatsApp summary to Nadine.
    """
    try:
        result = _post_to_gas({"action": "list_overdue_invoices", "sheet_id": SHEET_ID})
        overdue = result.get("overdue", []) or result.get("unpaid", [])

        if not overdue:
            send_safe_message(
                to=NADINE_WA,
                is_template=True,
                template_name=TPL_ADMIN_ALERT,
                variables=["✅ All invoices are fully paid. Enjoy your day! 😊"],
                label="invoices_all_paid"
            )
            return jsonify({"ok": True, "message": "All invoices are paid."})

        lines = []
        total_due = 0.0
        for rec in overdue:
            name = rec.get("client_name", "").strip()
            amt = float(rec.get("amount_due") or 0)
            if not name or amt <= 0:
                continue
            total_due += amt
            lines.append(f"{name} R{amt:,.0f}")

        summary = f"📋 PilatesHQ Invoices: {len(lines)} unpaid totalling R{total_due:,.0f}: " + "; ".join(lines)
        summary = " ".join(summary.split())

        send_safe_message(
            to=NADINE_WA,
            is_template=True,
            template_name=TPL_ADMIN_ALERT,
            variables=[summary],
            label="invoice_unpaid_summary"
        )

        log.info(f"✅ Unpaid invoice summary sent to Nadine ({len(lines)} clients).")
        return jsonify({
            "ok": True,
            "count": len(lines),
            "total_due": total_due,
            "overdue": overdue,
            "summary": summary
        })

    except Exception as e:
        log.error(f"❌ list_unpaid_invoices error: {e}")
        send_safe_message(
            to=NADINE_WA,
            is_template=True,
            template_name=TPL_ADMIN_ALERT,
            variables=[f"⚠️ Error fetching unpaid invoices: {e}"],
            label="invoice_unpaid_error"
        )
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# /invoices/test-send → Send or test WhatsApp invoice message
# ─────────────────────────────────────────────────────────────
@bp.route("/test-send", methods=["POST", "GET"])
def test_invoice_send():
    """
    Generates a sample PilatesHQ invoice message and sends via WhatsApp.
    Useful for verifying Meta template + formatting.
    """
    try:
        data = {}
        if request.method == "POST":
            data = request.get_json(force=True) or {}

        # Determine recipient
        to = data.get("to") or os.getenv("TEST_WA") or NADINE_WA
        now = datetime.now()
        month_name = now.strftime("%B %Y")  # e.g. "October 2025"

        # Build sample invoice string (Meta-safe single line)
        message = (
            f"📑 PilatesHQ Invoice – {month_name}: "
            f"02, 04 {now.strftime('%b')} Duo (R250)x2; "
            f"11, 18 {now.strftime('%b')} Single (R300)x2. "
            f"Total R1,100 | Paid R600 | Balance R500. "
            f"PDF: https://drive.google.com/abcd1234"
        )

        # Send via approved client template
        resp = send_safe_message(
            to=to,
            is_template=True,
            template_name=TPL_CLIENT_ALERT,
            variables=[message],
            label="invoice_test_send"
        )

        log.info(f"✅ Test invoice sent to {to}: {message}")
        return jsonify({"ok": True, "to": to, "message": message, "response": resp})

    except Exception as e:
        log.error(f"❌ test_invoice_send error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# Health Check
# ─────────────────────────────────────────────────────────────
@bp.route("", methods=["GET"])
def health():
    """Basic health check for invoices router."""
    return jsonify({
        "status": "ok",
        "service": "Invoices Router",
        "endpoints": [
            "/invoices/unpaid",
            "/invoices/test-send",
            "/invoices/mark-paid",
            "/invoices/review",
            "/invoices/send",
            "/invoices/edit"
        ]
    }), 200
