"""
router_webhook.py
──────────────────
Entry point for the /webhook endpoint.
Delegates admin, client, and prospect flows.
"""

import os
import logging
import json
from flask import Blueprint, request, Response, jsonify
from .utils import normalize_wa, send_whatsapp_text
from .db import get_session
from . import router_admin, router_client
from .prospect import start_or_resume
from .router_helpers import _create_client_record, _normalize_dob, _format_dob_display

log = logging.getLogger(__name__)
router_bp = Blueprint("router_webhook", __name__)

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "changeme")


@router_bp.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        # Meta verification
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token == VERIFY_TOKEN:
            return Response(challenge, status=200)
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
                return jsonify({"status": "ignored"}), 200

            msg = messages[0]
            from_wa = normalize_wa(msg.get("from"))
            msg_type = msg.get("type")
            text_in = msg.get("text", {}).get("body", "")

            # ── Interactive handling (flow/button replies)
            if msg_type == "interactive":
                return router_admin.handle_interactive(msg, from_wa)

            # ── Plain button
            if msg_type == "button":
                return router_admin.handle_button(msg, from_wa)

            # ── Admin vs Client vs Prospect
            admin_list = os.getenv("ADMIN_WA_LIST", "").split(",")
            if from_wa in [normalize_wa(x) for x in admin_list if x.strip()]:
                return router_admin.handle_admin(msg, from_wa, text_in)

            # Client
            client = router_client.client_get(from_wa)
            if client:
                return router_client.handle_client(msg, from_wa, text_in, client)

            # Prospect fallback
            start_or_resume(from_wa, text_in)
            return jsonify({"status": "ok", "role": "prospect"}), 200

        except Exception as e:
            log.exception("[Webhook] Handling failed")
            send_whatsapp_text(from_wa, f"⚠ Error: {e}")
            return jsonify({"status": "error", "error": str(e)}), 500
