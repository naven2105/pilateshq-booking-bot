# app/router.py
from flask import Blueprint, request, Response, jsonify
import os
import logging
import json
from datetime import datetime

from .utils import normalize_wa, send_whatsapp_text
from .invoices import send_invoice
from .admin_core import handle_admin_action
from .prospect import start_or_resume, _client_get, CLIENT_MENU
from .db import get_session
from sqlalchemy import text

router_bp = Blueprint("router", __name__)
log = logging.getLogger(__name__)

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "changeme")


def _format_dob(dob: str | None) -> str | None:
    """Format DOB to DD-MMM (drop year)."""
    if not dob:
        return None
    for fmt in ("%d %B %Y", "%d %b %Y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(dob, fmt)
            return dt.strftime("%d-%b")
        except Exception:
            continue
    return dob  # fallback raw string


def _create_client_record(name: str, mobile_entered: str, dob: str | None) -> str:
    """
    Insert new client and mark lead as converted.
    Returns admin confirmation message (not sent to client).
    """
    wa = normalize_wa(mobile_entered)
    with get_session() as s:
        # Check if already exists
        row = s.execute(
            text("SELECT id, name, birthday FROM clients WHERE wa_number=:wa"),
            {"wa": wa},
        ).first()
        if row:
            log.info("[CLIENT CREATE] Already exists id=%s wa=%s", row[0], wa)
            dob_fmt = _format_dob(str(row[2])) if row[2] else None
            msg = (
                f"ℹ️ Client already exists\n\n"
                f"Name: {row[1]}\n"
                f"Mobile: {mobile_entered}"
            )
            if dob_fmt:
                msg += f"\nDOB: {dob_fmt}"
            return msg

        # Insert new client
        s.execute(
            text(
                "INSERT INTO clients (name, wa_number, phone, birthday) "
                "VALUES (:n, :wa, :wa, :dob)"
            ),
            {"n": name, "wa": wa, "dob": dob},
        )
        log.info("[CLIENT CREATE] Inserted name=%s wa=%s", name, wa)

        # Mark lead as converted
        s.execute(
            text("UPDATE leads SET status='converted' WHERE wa_number=:wa"),
            {"wa": wa},
        )

        # Confirmation message for Nadine
        msg = (
            f"✅ New client registered\n\n"
            f"Name: {name}\n"
            f"Mobile: {mobile_entered}"
        )
        if dob:
            msg += f"\nDOB: {_format_dob(dob)}"
        return msg


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
            log.info("[Webhook][RAW MESSAGE] %s", msg)

            from_wa = msg.get("from")
            text_in = msg.get("text", {}).get("body", "")

            # ─────────────── Flow / NFM Form Replies ───────────────
            if msg.get("type") == "interactive":
                interactive = msg.get("interactive", {})
                itype = interactive.get("type")

                if itype in {"flow_reply", "nfm_reply"}:
                    try:
                        reply_data = interactive.get(itype, {})
                        log.info("[Webhook] Received %s: %s", itype, reply_data)

                        params = reply_data.get("response_json", {})
                        if isinstance(params, str):
                            try:
                                params = json.loads(params)
                            except Exception as e:
                                log.error("[%s] Failed to parse response_json: %s", itype, e)
                                params = {}

                        # Parse fields
                        client_name = (
                            params.get("Client Name")
                            or params.get("screen_0_Client_Name_0")
                            or params.get("name")
                        )
                        mobile = (
                            params.get("Mobile")
                            or params.get("screen_0_Mobile_1")
                            or params.get("phone")
                        )
                        dob = params.get("DOB") or params.get("screen_0_DOB_2")

                        log.info("[%s] Parsed fields → name=%s, mobile=%s, dob=%s", itype, client_name, mobile, dob)

                        if client_name and mobile:
                            msg_text = _create_client_record(client_name, mobile, dob)
                            send_whatsapp_text(from_wa, msg_text)
                        else:
                            send_whatsapp_text(
                                from_wa,
                                "⚠️ Client form reply could not be parsed. Please check logs.",
                            )

                        return jsonify({"status": "ok", "role": itype}), 200

                    except Exception:
                        log.exception("[Webhook] Failed to handle %s", itype)
                        send_whatsapp_text(
                            from_wa,
                            f"⚠️ Error handling client form ({itype}). Nadine please check logs.",
                        )
                        return jsonify({"status": "error", "role": itype}), 200

            # Normalize number
            wa = normalize_wa(from_wa)
            log.info("[Webhook] Message from %s: %r", wa, text_in)

            # Admin route
            admin_list = os.getenv("ADMIN_WA_LIST", "").split(",")
            if wa in [normalize_wa(x) for x in admin_list if x.strip()]:
                log.info("[Webhook] Routing as ADMIN: %s", wa)
                handle_admin_action(wa, msg.get("id"), text_in)
                return jsonify({"status": "ok", "role": "admin"}), 200

            # Client route
            client = _client_get(wa)
            if client:
                log.info("[Webhook] Routing as CLIENT: %s (%s)", wa, client["name"])
                send_whatsapp_text(wa, CLIENT_MENU.format(name=client["name"]))
                return jsonify({"status": "ok", "role": "client"}), 200

            # Prospect route
            log.info("[Webhook] Routing as PROSPECT: %s", wa)
            start_or_resume(wa, text_in)
            return jsonify({"status": "ok", "role": "prospect"}), 200

        except Exception as e:
            log.exception("[Webhook] Handling failed")
            return jsonify({"status": "error", "error": str(e)}), 500
