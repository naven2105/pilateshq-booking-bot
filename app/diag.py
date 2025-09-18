# app/diag.py

from flask import Blueprint, request, jsonify, url_for, Response
from .utils import _send_to_meta
from .invoices import (
    generate_invoice_pdf,
)

diag_bp = Blueprint("diag", __name__)

# ──────────────────────────────────────────────
# Invoice PDF preview
# ──────────────────────────────────────────────
@diag_bp.route("/diag/invoice-pdf")
def diag_invoice_pdf():
    client = request.args.get("client", "")
    month = request.args.get("month", "this month")
    pdf_bytes = generate_invoice_pdf(client, month)
    filename = f"Invoice_{client}_{month}.pdf".replace(" ", "_")
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f"inline; filename={filename}"}
    )

# ──────────────────────────────────────────────
# Monthly report PDF preview
# ──────────────────────────────────────────────
@diag_bp.route("/diag/monthly-report-pdf")
def diag_monthly_report_pdf():
    month = request.args.get("month", "this month")
    pdf_bytes = generate_monthly_report_pdf(month)
    filename = f"Monthly_Report_{month}.pdf".replace(" ", "_")
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f"inline; filename={filename}"}
    )
