# app/diag.py
from flask import Blueprint, request, jsonify, Response, url_for
from .utils import _send_to_meta
from .invoices import (
    generate_invoice_pdf,
    generate_invoice_whatsapp,
    generate_monthly_report_pdf,
    _fetch_client_name_from_number,
)

diag_bp = Blueprint("diag", __name__)

# ────────────────────────────────────────────────
# Client invoice via WhatsApp (lite message)
# ────────────────────────────────────────────────

@diag_bp.route("/diag/send_invoice_whatsapp")
def diag_send_invoice_whatsapp():
    """
    Send a lightweight WhatsApp invoice to a client.
    Usage: /diag/send_invoice_whatsapp?to=2773...&month=Sept
    """
    to = request.args.get("to")
    month = request.args.get("month", "this month")

    client_name = _fetch_client_name_from_number(to)
    if not client_name:
        return jsonify({"ok": False, "error": f"No client found for {to}"}), 404

    base_url = request.url_root.strip("/")
    message = generate_invoice_whatsapp(client_name, month, base_url)

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message},
    }

    ok, status, body = _send_to_meta(payload)
    return jsonify({"ok": ok, "status": status, "response": body, "preview": message})

# ────────────────────────────────────────────────
# PDF Invoice endpoint
# ────────────────────────────────────────────────

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

# ────────────────────────────────────────────────
# Monthly report (admin only)
# ────────────────────────────────────────────────

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
