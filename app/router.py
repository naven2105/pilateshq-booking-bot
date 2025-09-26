# app/router.py
from flask import Blueprint, request, Response, jsonify
import os
import logging

from .utils import normalize_wa, send_whatsapp_text
from .invoices import send_invoice
from .admin_core import handle_admin_action
from .prospect import start_or_resume, _client_get, CLIENT_MENU
from .db import get_session

router_bp = Blueprint("router", __name__)
log = logging.getLogger(__name__)

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "changeme")


@router_bp.route("/webhook", methods=["GET", "POST"])
def webhook():
    """Main WhatsApp webhook endpoint for Meta."""
    if request.method == "GET":
        # Meta verification challenge
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token == VERIFY_TOKEN:
            log.info("[Webhook] Verification succeeded")
            return Response(challenge, status=200)
        log.warning("[Webhook] Verification failed")
        return Response("Verification failed", status=403)

    if request.method == "POST":
        data = request.get_json(force=True, silent=True) or {}
        log.info("[Webhook] Incoming payload: %s", data)

        try:
            entry = data.get("entry", [])[0]
            changes = entry.get("changes", [])[0]
            value = changes.get("value", {})
            messages = value.get("messages", [])

            if not messages:
                log.info("[Webhook] No messages in payload")
                return jsonify({"status": "ignored"}), 200

            msg = messages[0]
            from_wa = msg.get("from")
            text_in = msg.get("text", {}).get("body", "")

            # Normalize number
            wa = normalize_wa(from_wa)
            log.info("[Webhook] Message from %s: %r", wa, text_in)

            # Check if this is an admin number
            admin_list = os.getenv("ADMIN_WA_LIST", "").split(",")
            if wa in [normalize_wa(x) for x in admin_list if x.strip()]:
                log.info("[Webhook] Routing as ADMIN: %s", wa)
                handle_admin_action(wa, msg.get("id"), text_in)
                return jsonify({"status": "ok", "role": "admin"}), 200

            # If known client, show client menu
            client = _client_get(wa)
            if client:
                log.info("[Webhook] Routing as CLIENT: %s (%s)", wa, client["name"])
                send_whatsapp_text(wa, CLIENT_MENU.format(name=client["name"]))
                return jsonify({"status": "ok", "role": "client"}), 200

            # Otherwise, treat as prospect
            log.info("[Webhook] Routing as PROSPECT: %s", wa)
            start_or_resume(wa, text_in)
            return jsonify({"status": "ok", "role": "prospect"}), 200

        except Exception as e:
            log.exception("[Webhook] Handling failed")
            return jsonify({"status": "error", "error": str(e)}), 500
