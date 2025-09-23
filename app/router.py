#app/router.py
from flask import Blueprint, request, Response, jsonify
from sqlalchemy import text
import os
import logging

from .utils import _send_to_meta, normalize_wa, send_whatsapp_text, safe_execute
from .invoices import generate_invoice_pdf, send_invoice
from .admin import handle_admin_action
from .admin_nudge import handle_admin_reply
from .prospect import start_or_resume, _client_get, CLIENT_MENU
from .db import get_session
from . import booking, faq, client_nlp

router_bp = Blueprint("router", __name__)
log = logging.getLogger(__name__)

ADMIN_NUMBER = os.getenv("ADMIN_NUMBER", "")
NADINE_WA = os.getenv("NADINE_WA", "")


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
      - Admin (incl. Nadine) → admin.py or admin_nudge.py
      - Known client → client features (invoice/bookings/etc.)
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
        from_wa = normalize_wa(msg["from"])
        text_in = msg.get("text", {}).get("body", "").strip()
    except Exception as e:
        log.exception("Webhook payload error")
        return jsonify({"error": f"invalid payload {e}"}), 400

    log.info(f"[WEBHOOK] from={from_wa} text={text_in!r}")

    # ─────────────── Admin ───────────────
    if from_wa in {normalize_wa(ADMIN_NUMBER), normalize_wa(NADINE_WA)}:
        log.debug(f"[ROUTER] matched ADMIN ({from_wa})")
        if from_wa == normalize_wa(NADINE_WA) and text_in.lower().startswith(("convert", "add ")):
            handle_admin_reply(from_wa, text_in)
            return "ok"

        handle_admin_action(from_wa, msg.get("id"), text_in, None)
        return "ok"

    # ─────────────── Known Client ───────────────
    with get_session() as s:
        row = s.execute(
            text("SELECT id FROM clients WHERE wa_number=:wa"),
            {"wa": from_wa},
        ).first()

    if row:
        log.debug(f"[ROUTER] matched CLIENT ({from_wa}) text={text_in!r}")
        parsed = client_nlp.parse_client_command(text_in)
        if parsed:
            intent = parsed["intent"]
            log.info(f"[CLIENT NLP] intent={intent}")
            if intent == "show_bookings":
                booking.show_bookings(from_wa)
                return "ok"
            if intent == "get_invoice":
                send_invoice(from_wa)
                return "ok"
            if intent == "faq":
                faq.show_faq(from_wa)
                return "ok"
            if intent == "contact_admin":
                client = _client_get(from_wa)
                name = client.get("name", "there") if client else "there"
                safe_execute(send_whatsapp_text, from_wa,
                    "👍 Got it! Nadine will contact you shortly.",
                    label="client_contact_admin"
                )
                if NADINE_WA:
                    safe_execute(send_whatsapp_text, NADINE_WA,
                        f"📞 Client requested contact: {name} ({from_wa})",
                        label="notify_admin_contact"
                    )
                return "ok"

        if text_in == "1":
            booking.show_bookings(from_wa)
            return "ok"
        if text_in == "2":
            send_invoice(from_wa)
            return "ok"
        if text_in == "3":
            faq.show_faq(from_wa)
            return "ok"
        if text_in == "0":
            client = _client_get(from_wa)
            name = client.get("name", "there") if client else "there"
            safe_execute(send_whatsapp_text, from_wa,
                "👍 Got it! Nadine will contact you shortly.",
                label="client_menu_contact"
            )
            if NADINE_WA:
                safe_execute(send_whatsapp_text, NADINE_WA,
                    f"📞 Client requested contact: {name} ({from_wa})",
                    label="notify_admin_menu"
                )
            return "ok"

        client = _client_get(from_wa)
        name = client.get("name", "there") if client else "there"
        safe_execute(send_whatsapp_text, from_wa,
            "🤖 Thanks for your message! Nadine will follow up with you shortly.",
            label="client_fallback"
        )
        if NADINE_WA:
            forward_msg = (
                f"📩 *Client message*\n"
                f"👤 {name} ({from_wa})\n"
                f"💬 \"{text_in}\""
            )
            safe_execute(send_whatsapp_text, NADINE_WA, forward_msg, label="forward_client_msg")
        return "ok"

    # ─────────────── Prospect ───────────────
    log.debug(f"[ROUTER] matched PROSPECT ({from_wa}) text={text_in!r}")
    start_or_resume(from_wa, text_in)
    return "ok"
