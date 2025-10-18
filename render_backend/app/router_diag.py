# app/router_diag.py
"""
router_diag.py
───────────────────────────────────────────────
Handles diagnostic and utility routes such as
invoice PDF rendering for client view.
"""

import io
from flask import Blueprint, request, send_file, jsonify
from .invoices import generate_invoice_pdf

bp = Blueprint("diag_bp", __name__)

@bp.route("/diag/invoice-pdf", methods=["GET"])
def invoice_pdf():
    """
    Generates and serves an invoice PDF dynamically based on query params.
    Example:
    /diag/invoice-pdf?client=Fatima%20Khan&month=Oct%202025&mobile=27720000000
    """
    try:
        client = request.args.get("client", "Unknown Client")
        month = request.args.get("month", "this month")
        mobile = request.args.get("mobile", "N/A")

        pdf_bytes = generate_invoice_pdf(client, mobile, month)
        return send_file(
            io.BytesIO(pdf_bytes),
            as_attachment=False,
            download_name=f"Invoice_{client.replace(' ', '_')}_{month}.pdf",
            mimetype="application/pdf"
        )
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
