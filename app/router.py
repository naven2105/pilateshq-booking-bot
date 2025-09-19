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

# Admin numbers list (comma-separated in env)
ADMIN_WA_LIST = os.getenv("ADMIN_WA_LIST", "").split(",")


def _is_client(wa: str) -> bool:
    """Return True if wa_number exists in clients table."""
    with get_session() as s:
        row = s.execute(
            text("SELECT id FROM clients WHERE wa_number=:wa"),
            {"wa": wa},
        ).first()
        return row is not None


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
    Routes:
      • Admin → admin actions
      • Existing client → invoices/schedule/etc.
      • Unknown number → prospect onboarding
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
        from_wa = normalize_wa(msg["from"])
        text = msg.get("text", {}).get("body", "").strip()
        msg_id = msg.get("id")
    except Exception as e:
        return jsonify({"error": f"invalid payload {e}"}), 400

    base_url = request.url_root.strip("/")

    # ──────────────── Admin ────────────────
    if from_wa in ADMIN_WA_LIST:
        handle_admin_action(from_wa, msg_id, text)
        return "ok"

    # ──────────────── Existing Client ────────────────
    if _is_client(from_wa):
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

        # fallback client menu
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

    # ──────────────── Prospect (new number) ────────────────
    start_or_resume(from_wa, text)
    return "ok"
