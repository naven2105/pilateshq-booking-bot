from flask import Blueprint, request, Response, jsonify
from .utils import _send_to_meta
from .invoices import generate_invoice_pdf, generate_invoice_whatsapp

router_bp = Blueprint("router", __name__)

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

@router_bp.route("/webhook", methods=["POST"])
def webhook():
    """
    Handle incoming WhatsApp messages.
    Supports:
      • "invoice" → current month invoice
      • "invoice Sept" → invoice for specific month
      • fallback → friendly help menu
    """
    data = request.get_json(force=True, silent=True) or {}
    try:
        entry = data["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]
        messages = value.get("messages", [])
        if not messages:
            return "ok"

        msg = messages[0]
        from_wa = msg["from"]  # client phone
        text = msg.get("text", {}).get("body", "").strip()
    except Exception as e:
        return jsonify({"error": f"invalid payload {e}"}), 400

    base_url = request.url_root.strip("/")

    # ──────────────── Command: invoice ────────────────
    if text.lower().startswith("invoice"):
        parts = text.split(maxsplit=1)
        month_spec = parts[1] if len(parts) > 1 else "this month"
        message = generate_invoice_whatsapp(from_wa, month_spec, base_url)

        payload = {
            "messaging_product": "whatsapp",
            "to": from_wa,
            "type": "text",
            "text": {"body": message},
        }
        _send_to_meta(payload)
        return "ok"

    # ──────────────── Fallback ────────────────
    fallback_msg = (
        "🤖 Sorry, I didn’t understand that.\n"
        "Here are some things you can ask me:\n\n"
        "• invoice [month] → Get your invoice (e.g. 'invoice Sept')\n"
        "• invoice → Get your invoice for this month\n"
        "• report → Get your monthly session report\n"
        "• payment → View your payment status\n"
        "• schedule → View your weekly session schedule\n"
        "• cancel → Cancel a session\n"
    )

    payload = {
        "messaging_product": "whatsapp",
        "to": from_wa,
        "type": "text",
        "text": {"body": fallback_msg},
    }
    _send_to_meta(payload)
    return "ok"
