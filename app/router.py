# app/router.py
import os
import logging
from flask import Blueprint, request, Response, jsonify
from sqlalchemy import text

from .utils import _send_to_meta, normalize_wa, send_whatsapp_text
from .invoices import generate_invoice_pdf, send_invoice
from .admin import handle_admin_action
from .admin_nudge import handle_admin_reply   # ✅ lead conversion / add logic
from .prospect import start_or_resume, _client_get, CLIENT_MENU
from .db import get_session
from . import booking, faq, client_nlp

router_bp = Blueprint("router", __name__)
log = logging.getLogger(__name__)

ADMIN_NUMBER = os.getenv("ADMIN_NUMBER", "")  # e.g. 27843131635
NADINE_WA = os.getenv("NADINE_WA", "")


# ─────────────── Invoice diagnostics ───────────────
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


# ─────────────── New diagnostic test endpoints ───────────────
@router_bp.route("/diag/test-webhook", methods=["POST"])
def diag_test_webhook():
    """
    Simulate webhook handling without sending anything to Meta.
    Useful for debugging routing with sample payloads.
    """
    data = request.get_json(force=True, silent=True) or {}
    log.info("[DIAG TEST-WEBHOOK] incoming test payload: %s", data)

    try:
        entry = data.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])
        if not messages:
            return jsonify({"status": "ok", "note": "no messages"}), 200
        msg = messages[0]
        from_wa = normalize_wa(msg.get("from", ""))
        text_in = (msg.get("text", {}) or {}).get("body", "").strip()
    except Exception as e:
        log.exception("Failed to parse test payload")
        return jsonify({"status": "error", "error": str(e)}), 400

    return jsonify({
        "status": "ok",
        "from": from_wa,
        "text": text_in,
        "routed_to": (
            "admin" if from_wa in {normalize_wa(ADMIN_NUMBER), normalize_wa(NADINE_WA)}
            else "client" if _client_get(from_wa)
            else "prospect"
        )
    })


@router_bp.route("/diag/test-leads")
def diag_test_leads():
    """Return all leads (read-only) for debugging."""
    with get_session() as s:
        rows = s.execute(
            text("SELECT id, wa_number, name, status FROM leads ORDER BY id DESC LIMIT 20")
        ).mappings().all()
    return jsonify([dict(r) for r in rows])


@router_bp.route("/diag/test-clients")
def diag_test_clients():
    """Return all clients (read-only) for debugging."""
    with get_session() as s:
        rows = s.execute(
            text("SELECT id, wa_number, name FROM clients ORDER BY id DESC LIMIT 20")
        ).mappings().all()
    return jsonify([dict(r) for r in rows])


@router_bp.route("/diag/test-send")
def diag_test_send():
    """
    Send a test WhatsApp message.
    Example: /diag/test-send?to=2773...&msg=Hello
    """
    to = request.args.get("to")
    msg = request.args.get("msg", "Hello from test-send")
    if not to:
        return jsonify({"error": "missing to param"}), 400
    try:
        send_whatsapp_text(normalize_wa(to), msg)
        return jsonify({"ok": True, "to": to, "msg": msg})
    except Exception as e:
        log.exception("test-send failed")
        return jsonify({"ok": False, "error": str(e)})


# ─────────────── Webhook ───────────────
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
    log.info("[WEBHOOK RAW] incoming payload: %s", data)

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
        log.exception("Failed to parse webhook payload")
        return jsonify({"error": f"invalid payload {e}"}), 400

    # Admin handling
    if from_wa in {normalize_wa(ADMIN_NUMBER), normalize_wa(NADINE_WA)}:
        if from_wa == normalize_wa(NADINE_WA) and text_in.lower().startswith(("convert", "add ")):
            handle_admin_reply(from_wa, text_in)
            return "ok"
        handle_admin_action(from_wa, msg.get("id"), text_in, None)
        return "ok"

    # Known client
    with get_session() as s:
        row = s.execute(text("SELECT id FROM clients WHERE wa_number=:wa"), {"wa": from_wa}).first()

    if row:
        parsed = client_nlp.parse_client_command(text_in)
        if parsed:
            intent = parsed["intent"]
            if intent == "show_bookings":
                booking.show_bookings(from_wa); return "ok"
            if intent == "get_invoice":
                send_invoice(from_wa); return "ok"
            if intent == "faq":
                faq.show_faq(from_wa); return "ok"
            if intent == "contact_admin":
                client = _client_get(from_wa)
                name = client.get("name", "there") if client else "there"
                send_whatsapp_text(from_wa, "👍 Got it! Nadine will contact you shortly.")
                if NADINE_WA:
                    send_whatsapp_text(NADINE_WA, f"📞 Client requested contact: {name} ({from_wa})")
                return "ok"

        # Numeric menu
        if text_in == "1": booking.show_bookings(from_wa); return "ok"
        if text_in == "2": send_invoice(from_wa); return "ok"
        if text_in == "3": faq.show_faq(from_wa); return "ok"
        if text_in == "0":
            client = _client_get(from_wa)
            name = client.get("name", "there") if client else "there"
            send_whatsapp_text(from_wa, "👍 Got it! Nadine will contact you shortly.")
            if NADINE_WA:
                send_whatsapp_text(NADINE_WA, f"📞 Client requested contact: {name} ({from_wa})")
            return "ok"

        # Fallback → forward to Nadine
        client = _client_get(from_wa)
        name = client.get("name", "there") if client else "there"
        send_whatsapp_text(from_wa, "🤖 Thanks for your message! Nadine will follow up with you shortly.")
        if NADINE_WA:
            forward_msg = f"📩 *Client message*\n👤 {name} ({from_wa})\n💬 \"{text_in}\""
            send_whatsapp_text(NADINE_WA, forward_msg)
        return "ok"

    # Prospect
    start_or_resume(from_wa, text_in)
    return "ok"
