"""
invoices_router.py – Phase 5 (Final)
────────────────────────────────────────────
Adds:
 • /invoices/unpaid → returns all unpaid or partial invoices
 • Streamlined “unpaid invoices” WhatsApp summary for Nadine
────────────────────────────────────────────
"""

import os, logging, requests
from flask import Blueprint, request, jsonify
from .utils import send_safe_message
import requests

bp = Blueprint("invoices_bp", __name__)
log = logging.getLogger(__name__)


# ── Environment ──────────────────────────────────────────────
NADINE_WA = os.getenv("NADINE_WA", "")
GAS_INVOICE_URL = os.getenv("GAS_INVOICE_URL", "")
SHEET_ID = os.getenv("CLIENT_SHEET_ID", "")
TPL_ADMIN_ALERT = "admin_generic_alert_us"   # ✅ Approved template


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

        # Build plain-text and Meta-safe summaries
        lines = []
        total_due = 0.0
        for rec in overdue:
            name = rec.get("client_name", "").strip()
            amt = float(rec.get("amount_due") or 0)
            if not name or amt <= 0:
                continue
            total_due += amt
            lines.append(f"{name} R{amt:,.0f}")

        # Meta-safe one-line message (no newlines)
        summary = f"📋 PilatesHQ Invoices: {len(lines)} unpaid totalling R{total_due:,.0f}: " + "; ".join(lines)
        summary = " ".join(summary.split())  # remove tabs/newlines

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
            "/invoices/mark-paid",
            "/invoices/review",
            "/invoices/send",
            "/invoices/edit"
        ]
    }), 200

# ─────────────────────────────────────────────────────────────
# ROUTE: Return unpaid/underpaid invoices from Google Apps Script
# ─────────────────────────────────────────────────────────────
@bp.route("/unpaid", methods=["GET"])
def get_unpaid_invoices():
    """
    Queries Google Apps Script endpoint for unpaid invoices.
    Expected GAS endpoint action: 'get_unpaid_invoices'
    Returns list of {client_name, amount_due}
    """
    if not GAS_INVOICE_URL:
        log.warning("⚠️ GAS_INVOICE_URL not configured.")
        return jsonify({"ok": False, "error": "Missing GAS_INVOICE_URL"}), 500

    try:
        payload = {"action": "get_unpaid_invoices", "sheet_id": SHEET_ID}
        resp = requests.post(GAS_INVOICE_URL, json=payload, timeout=20)
        if resp.status_code != 200:
            return jsonify({"ok": False, "error": f"GAS returned {resp.status_code}"}), resp.status_code

        data = resp.json()
        unpaid = data.get("unpaid", [])
        overdue = [i for i in unpaid if float(i.get("amount_due", 0)) > 0]
        log.info(f"🧾 Retrieved {len(overdue)} unpaid invoices from GAS.")

        return jsonify({"ok": True, "overdue": overdue})

    except Exception as e:
        log.error(f"❌ Error fetching unpaid invoices: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500