"""
invoices_router.py – Phase 5
────────────────────────────────────────────
Adds:
 • /invoices/unpaid → returns all unpaid or partial invoices
 • Streamlined “unpaid invoices” WhatsApp summary for Nadine
────────────────────────────────────────────
"""

import os, logging, requests
from flask import Blueprint, request, jsonify
from .utils import send_safe_message

bp = Blueprint("invoices_bp", __name__)
log = logging.getLogger(__name__)

# ── Environment ──────────────────────────────────────────────
NADINE_WA = os.getenv("NADINE_WA", "")
GAS_INVOICE_URL = os.getenv("GAS_INVOICE_URL", "")
SHEET_ID = os.getenv("CLIENT_SHEET_ID", "")

# ─────────────────────────────────────────────────────────────
# Utility: Unified Apps Script POST
# ─────────────────────────────────────────────────────────────
def _post_to_gas(payload: dict) -> dict:
    try:
        if not GAS_INVOICE_URL:
            raise ValueError("Missing GAS_INVOICE_URL env.")
        r = requests.post(GAS_INVOICE_URL, json=payload, timeout=15)
        if not r.ok:
            log.error(f"Apps Script HTTP {r.status_code}: {r.text}")
            return {"ok": False, "error": f"Apps Script HTTP {r.status_code}"}
        return r.json()
    except Exception as e:
        log.error(f"[invoices_router] GAS POST failed: {e}")
        return {"ok": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────
# /invoices/unpaid  → triggered by “unpaid invoices”
# ─────────────────────────────────────────────────────────────
@bp.route("/invoices/unpaid", methods=["POST"])
def list_unpaid_invoices():
    """Return a summary list of all unpaid or partially paid invoices."""
    try:
        result = _post_to_gas({"action": "list_overdue_invoices", "sheet_id": SHEET_ID})
        overdue = result.get("overdue", [])

        if not overdue:
            send_safe_message(to=NADINE_WA, message="✅ All invoices are fully paid!")
            return jsonify({"ok": True, "message": "All invoices are paid."})

        # Build WhatsApp summary message
        lines = ["📋 *Unpaid Invoices Summary:*"]
        for rec in overdue:
            name = rec.get("client_name", "")
            amt = rec.get("amount_due", "")
            status = (rec.get("status") or "").replace("_", " ").capitalize()
            if name and amt:
                lines.append(f"• {name} — R{amt} ({status})")

        msg = "\n".join(lines)
        send_safe_message(to=NADINE_WA, message=msg, label="invoice_unpaid_list")

        return jsonify({"ok": True, "count": len(overdue), "message": msg})
    except Exception as e:
        log.error(f"list_unpaid_invoices error: {e}")
        send_safe_message(to=NADINE_WA, message=f"⚠️ Error fetching unpaid invoices: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# Health Check
# ─────────────────────────────────────────────────────────────
@bp.route("/invoices", methods=["GET"])
def health():
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
