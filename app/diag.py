#app/diag.py
from flask import Blueprint, request, jsonify, url_for, Response
from .utils import _send_to_meta
from .invoices import (
    generate_invoice_text,
    generate_invoice_html,
    generate_invoice_pdf,
    generate_monthly_report_pdf,
)

diag_bp = Blueprint("diag", __name__)

# ────────────────────────────────────────────────
# Monthly report (PDF only)
# ────────────────────────────────────────────────

@diag_bp.route("/diag/send_monthly_report_pdf")
def diag_send_monthly_report_pdf():
    """
    Send Nadine a WhatsApp link to download the monthly report (PDF).
    Usage:
      /diag/send_monthly_report_pdf?to=27735534607&month=Sept%202025
    """
    to = request.args.get("to")
    month = request.args.get("month", "this month")

    report_url = url_for("diag_monthly_report_pdf", month=month, _external=True)
    message = f"📑 PilatesHQ Monthly Report ({month})\nDownload PDF here: {report_url}"

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message},
    }

    ok, status, body = _send_to_meta(payload)
    return jsonify({"ok": ok, "status": status, "response": body, "preview": message})


@diag_bp.route("/diag/monthly-report-pdf")
def diag_monthly_report_pdf():
    """
    Generate the monthly report (PDF) and return as downloadable file.
    """
    month = request.args.get("month", "this month")
    pdf_bytes = generate_monthly_report_pdf(month)
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-disposition": f"attachment; filename=monthly_report_{month}.pdf"}
    )
