import logging
import re
from flask import Blueprint, request, jsonify, url_for

from .settings import ADMIN_NUMBER
from .utils import _send_to_meta
from .admin_commands import (
    handle_invoice_command,
    handle_payment_command,
    handle_payment_confirmation,
)
from .invoices import generate_invoice_text, generate_invoice_whatsapp

logger = logging.getLogger(__name__)
router_bp = Blueprint("router", __name__)

# ────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────

def send_text_message(to: str, body: str):
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body},
    }
    ok, status, resp = _send_to_meta(payload)
    if not ok:
        logger.error("[SendTextError] to=%s status=%s resp=%s", to, status, resp)
    return {"ok": ok, "status": status, "resp": resp}

def lookup_client_name(wa_number: str) -> str | None:
    """
    Map WhatsApp number → client name.
    Requires clients table to have phone field.
    """
    from sqlalchemy import text as sql_text
    from .db import db_session
    sql = sql_text("SELECT name FROM clients WHERE phone = :phone LIMIT 1")
    with db_session() as s:
        row = s.execute(sql, {"phone": wa_number}).first()
    return row[0] if row else None

# ────────────────────────────────────────────────
# Webhook handler
# ────────────────────────────────────────────────

@router_bp.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True, silent=True) or {}
    try:
        entry = data["entry"][0]
        change = entry["changes"][0]
        value = change["value"]
        msg = value["messages"][0]

        from_number = msg["from"]
        msg_type = msg.get("type", "text")
        body = msg["text"]["body"].strip() if msg_type == "text" else ""

        logger.info("[Webhook] from=%s body=%s", from_number, body)

        # ───────────────────────────────
        # Admin commands (Nadine)
        # ───────────────────────────────
        if from_number == ADMIN_NUMBER:
            # 1. Invoice commands
            invoice_reply = handle_invoice_command(from_number, body)
            if invoice_reply:
                send_text_message(from_number, invoice_reply)
                return jsonify({"status": "ok"})

            # 2. Payment logging
            pay_reply = handle_payment_command(from_number, body)
            if pay_reply:
                send_text_message(from_number, pay_reply)
                return jsonify({"status": "ok"})

            # 3. Payment confirmation
            confirm_reply = handle_payment_confirmation(from_number, body)
            if confirm_reply:
                send_text_message(from_number, confirm_reply)
                return jsonify({"status": "ok"})

        # ───────────────────────────────
        # Client flows
        # ───────────────────────────────
        else:
            # Client requests invoice
            m = re.match(r"^invoice\s+(.+)$", body, flags=re.I)
            if m:
                month_spec = m.group(1)
                client_name = lookup_client_name(from_number)
                if not client_name:
                    send_text_message(
                        from_number,
                        "⚠️ Sorry, we could not find your account. Please contact Nadine."
                    )
                    return jsonify({"status": "ok"})

                # Generate short WhatsApp invoice
                base_url = request.url_root.rstrip("/")
                invoice_msg = generate_invoice_whatsapp(client_name, month_spec, base_url)
                send_text_message(from_number, invoice_msg)
                return jsonify({"status": "ok"})

            # Default reply
            send_text_message(
                from_number,
                "🤖 Thanks for your message! A team member will assist you shortly."
            )

        return jsonify({"status": "ignored"})

    except Exception as e:
        logger.exception("[WebhookError] %s", str(e))
        return jsonify({"error": str(e)}), 500

# ────────────────────────────────────────────────
# Webhook verification
# ────────────────────────────────────────────────

@router_bp.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    VERIFY_TOKEN = "your-verify-token"  # set in env/config
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403
