# app/router.py
from flask import Blueprint, request, Response
from .invoices import generate_invoice_pdf, generate_invoice_whatsapp
from .utils import _send_to_meta
from .db import db_session
from sqlalchemy import text
import re

router_bp = Blueprint("router", __name__)

# ────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────

def get_client_name_from_number(phone: str) -> str:
    """
    Look up client name by their WhatsApp number.
    Falls back to returning the number if no match.
    """
    sql = text("SELECT name FROM clients WHERE phone = :phone LIMIT 1")
    with db_session() as s:
        name = s.execute(sql, {"phone": phone}).scalar()
    return name or phone

# ────────────────────────────────────────────────
# Invoice PDF (for download)
# ────────────────────────────────────────────────

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

# ────────────────────────────────────────────────
# WhatsApp message handler
# ────────────────────────────────────────────────

@router_bp.route("/webhook", methods=["POST"])
def webhook():
    """
    Handle incoming WhatsApp messages.
    If client types "invoice [month]" → send lite WhatsApp invoice.
    """
    data = request.get_json(force=True, silent=True) or {}
    entry = data.get("entry", [])[0]
    changes = entry.get("changes", [])[0]
    value = changes.get("value", {})
    messages = value.get("messages", [])

    if not messages:
        return {"status": "ignored"}, 200

    msg = messages[0]
    from_wa = msg["from"]  # WhatsApp number (e.g. 27735534607)
    body = msg.get("text", {}).get("body", "").strip().lower()

    # Match "invoice" command
    match = re.match(r"^invoice(?:\s+(.*))?$", body)
    if match:
        month_spec = match.group(1) or "this month"
        client_name = get_client_name_from_number(from_wa)

        base_url = request.url_root.strip("/")
        message = generate_invoice_whatsapp(client_name, month_spec, base_url)

        payload = {
            "messaging_product": "whatsapp",
            "to": from_wa,
            "type": "text",
            "text": {"body": message},
        }
        _send_to_meta(payload)
        return {"status": "invoice_sent"}, 200

    # Default fallback
    return {"status": "unhandled"}, 200
