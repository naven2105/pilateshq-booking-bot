# app/router.py
from flask import Blueprint, request, Response, jsonify
from .utils import _send_to_meta, normalize_wa
from .invoices import generate_invoice_pdf, generate_invoice_whatsapp
from .admin import handle_admin_action
from .prospect import start_or_resume
from .db import get_session
from sqlalchemy import text
import os

router_bp = Blueprint("router", __name__)

ADMIN_NUMBER = os.getenv("ADMIN_NUMBER", "")  # e.g. 27843131635


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
    Routing:
      - Admin → admin.py
      - Known client → client features (invoice/report/etc.)
      - Unknown → prospect.py onboarding
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
        from_wa = normalize_wa(msg["from"])  # sender WA number
        text_in = msg.get("text", {}).get("body", "").strip()
    except Exception as e:
        return jsonify({"error": f"invalid payload {e}"}), 400

    base_url = request.url_root.strip("/")

    # ─────────────── Admin ───────────────
    if from_wa == normalize_wa(ADMIN_NUMBER):
        handle_admin_action(from_wa, msg.get("id"), text_in, None)
        return "ok"

    # ─────────────── Known Client ───────────────
    with get_session() as s:
        row = s.execute(
            text("SELECT id FROM clients WHERE wa_number=:wa"),
            {"wa": from_wa},
        ).first()

    if row:
        # Commands for existing clients
        if text_in.lower().startswith("invoice"):
            parts = text_in.split(maxsplit=1)
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

        # (future: report, payment, schedule, cancel)

        # fallback for clients
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

    # ─────────────── Prospect (unknown) ───────────────
    start_or_resume(from_wa, text_in)
    return "ok"
