from flask import Blueprint, request, Response, jsonify
from .utils import _send_to_meta
from .invoices import generate_invoice_pdf, _fetch_client_name_by_phone

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

    if text.lower().startswith("invoice"):
        parts = text.split(maxsplit=1)
        month_spec = parts[1] if len(parts) > 1 else "this month"

        # 🔹 resolve client name from phone
        client_name = _fetch_client_name_by_phone(from_wa)

        # 🔹 construct a warm lite invoice
        message = f"📑 PilatesHQ Invoice — {client_name}\nPeriod: {month_spec.title()}\n\n(Invoice details here…)\n\n🔗 Download PDF if needed: {base_url}/diag/invoice-pdf?client={client_name}&month={month_spec}"

        payload = {
            "messaging_product": "whatsapp",
            "to": from_wa,
            "type": "text",
            "text": {"body": message},
        }
        _send_to_meta(payload)
        return "ok"

    # fallback
    fallback_msg = (
        "🤖 Sorry, I didn’t understand that.\n"
        "Here are some things you can ask me:\n\n"
        "• invoice [month] → Get your invoice (e.g. 'invoice Sept')\n"
        "• invoice → Get your invoice for this month\n"
        "• report → Get your monthly report\n"
        "• payment → View your payment status\n"
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": from_wa,
        "type": "text",
        "text": {"body": fallback_msg},
    }
    _send_to_meta(payload)
    return "ok"
