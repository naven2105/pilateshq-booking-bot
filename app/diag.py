# app/diag.py
from flask import Blueprint, request, jsonify, url_for, Response
from .utils import _send_to_meta
from .invoices import (
    generate_invoice_pdf,
    generate_invoice_whatsapp,
    generate_monthly_report_pdf,
)

diag_bp = Blueprint("diag", __name__)

# ────────────────────────────────────────────────
# Per-client invoice (WhatsApp Lite + PDF)
# ────────────────────────────────────────────────

@diag_bp.route("/diag/send_invoice_whatsapp")
def diag_send_invoice_whatsapp():
    """
    Send a WhatsApp-friendly lite invoice to a client.
    Usage:
      /diag/send_invoice_whatsapp?to=27735534607&client=NAME&month=Sept%202025
    """
    to = request.args.get("to")
    client = request.args.get("client", "")
    month = request.args.get("month", "this month")

    base_url = request.url_root.strip("/")
    message = generate_invoice_whatsapp(client, month, base_url)

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message},
    }

    ok, status, body = _send_to_meta(payload)
    return jsonify({"ok": ok, "status": status, "response": body, "preview": message})


@diag_bp.route("/diag/invoice-pdf")
def diag_invoice_pdf():
    """
    Generate and return a client invoice in PDF format.
    Usage:
      /diag/invoice-pdf?client=NAME&month=Sept%202025
    """
    client = request.args.get("client", "")
    month = request.args.get("month", "this month")

    pdf_bytes = generate_invoice_pdf(client, month)
    filename = f"Invoice_{client}_{month}.pdf".replace(" ", "_")

    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f"inline; filename={filename}"}
    )

# ────────────────────────────────────────────────
# Monthly report (PDF for Nadine)
# ────────────────────────────────────────────────

@diag_bp.route("/diag/send_monthly_report_pdf")
def diag_send_monthly_report_pdf():
    """
    Send Nadine a WhatsApp link to view the monthly report (PDF).
    Usage:
      /diag/send_monthly_report_pdf?to=27735534607&month=Sept%202025
    """
    to = request.args.get("to")
    month = request.args.get("month", "this month")

    report_url = url_for("diag_monthly_report_pdf", month=month, _external=True)
    message = f"📑 PilatesHQ Monthly Report ({month})\nClick here to view (PDF): {report_url}"

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
    Return the monthly report as a PDF (admin only).
    """
    month = request.args.get("month", "this month")
    pdf_bytes = generate_monthly_report_pdf(month)
    filename = f"Monthly_Report_{month}.pdf".replace(" ", "_")

    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f"inline; filename={filename}"}
    )
