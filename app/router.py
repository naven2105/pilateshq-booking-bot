# app/router.py
from flask import Blueprint, request, Response
from .invoices import generate_invoice_pdf
from .utils import _send_to_meta

router_bp = Blueprint("router", __name__)

# ─────────────────────────────
# Serve invoice PDF directly
# ─────────────────────────────
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

# ─────────────────────────────
# Webhook: handle WhatsApp messages
# ─────────────────────────────
@router_bp.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    sender = data.get("from")  # WhatsApp number of client
    msg_text = data.get("text", {}).get("body", "").strip().lower()

    # Simple trigger: "invoice"
    if msg_text.startswith("invoice"):
        client_name = sender   # fallback if phone not mapped to a client
        month_spec = "this month"

        # Build WhatsApp-lite invoice message
        pdf_url = f"{request.url_root}diag/invoice-pdf?client={client_name}&month={month_spec}"
        message = (
            f"📑 PilatesHQ Invoice — {client_name}\n"
            f"Period: {month_spec}\n\n"
            f"💳 Banking details:\n"
            f"Pilates HQ Pty Ltd\nAbsa Bank\nCurrent Account\nAccount No: 41171518 87\n\n"
            f"Notes:\n• Use your name as reference\n• Send POP once paid\n\n"
            f"🔗 Download full invoice (PDF): {pdf_url}"
        )

        payload = {
            "messaging_product": "whatsapp",
            "to": sender,
            "type": "text",
            "text": {"body": message},
        }
        ok, status, body = _send_to_meta(payload)
        return {"ok": ok, "status": status, "body": body}

    # Default response
    return {"ok": True, "note": "No action"}
