# app/router.py
from flask import Blueprint, request, Response, jsonify
from .utils import _send_to_meta
from .invoices import (
    generate_invoice_pdf,
    generate_invoice_whatsapp,
    _fetch_client_name_by_phone,   # ✅ NEW import
)
import re

router_bp = Blueprint("router", __name__)

# ────────────────────────────────────────────────
# Invoice PDF
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
# Webhook (handles invoices, POP, fallback, etc.)
# ────────────────────────────────────────────────
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
        from_wa = msg["from"]
        text = msg.get("text", {}).get("body", "").strip()
        msg_type = msg.get("type", "text")
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

    # ──────────────── POP detection ────────────────
    pop_keywords = ["pop", "proof of payment", "paid", "deposit", "eft", "payment"]
    is_pop = False

    if msg_type in ("image", "document"):
        is_pop = True
    elif any(k in text.lower() for k in pop_keywords):
        is_pop = True

    if is_pop:
        client_name = _fetch_client_name_by_phone(from_wa)
        # Ask client for amount + reference
        ask_msg = (
            "💰 Thanks for sending your payment/POP.\n"
            "Please reply with:\n"
            "• Amount paid\n"
            "• Beneficiary reference used"
        )
        _send_to_meta({
            "messaging_product": "whatsapp",
            "to": from_wa,
            "type": "text",
            "text": {"body": ask_msg},
        })

        # Notify Nadine (admin)
        admin_msg = (
            f"📥 POP received from {client_name} ({from_wa}).\n"
            f"Awaiting amount + reference confirmation."
        )
        _send_to_meta({
            "messaging_product": "whatsapp",
            "to": "27627597357",  # Nadine
            "type": "text",
            "text": {"body": admin_msg},
        })
        return "ok"

    # ──────────────── Fallback ────────────────
    fallback_msg = (
        "🤖 Sorry, I didn’t understand that.\n"
        "Here are some things you can ask me:\n\n"
        "• invoice [month] → Get your invoice (e.g. 'invoice Sept')\n"
        "• invoice → Get your invoice for this month\n"
        "• report → View your monthly session report\n"
        "• payment → Check your payment status\n"
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
