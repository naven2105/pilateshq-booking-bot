from flask import Blueprint, request, Response
from .invoices import generate_invoice_html, generate_invoice_pdf

router_bp = Blueprint("router", __name__)

@router_bp.route("/diag/invoice-html")
def diag_invoice_html():
    client = request.args.get("client", "")
    month = request.args.get("month", "this month")
    html = generate_invoice_html(client, month)
    return Response(html, mimetype="text/html")

@router_bp.route("/diag/invoice-pdf")
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
