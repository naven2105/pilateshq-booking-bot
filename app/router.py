# app/router.py
from flask import Blueprint, request, Response, jsonify
import os
import logging
import json
from datetime import datetime

from .utils import normalize_wa, send_whatsapp_text, safe_execute
from .admin_core import handle_admin_action
from .prospect import start_or_resume, _client_get, CLIENT_MENU
from .db import get_session
from . import admin_nudge
from sqlalchemy import text

router_bp = Blueprint("router", __name__)
log = logging.getLogger(__name__)

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "changeme")


# ── Helpers ──────────────────────────────────────────────
def _normalize_dob(dob: str | None) -> str | None:
    if not dob:
        return None
    dob = dob.strip()
    for fmt in ("%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(dob, fmt).strftime("%Y-%m-%d")
        except Exception:
            pass
    for fmt in ("%d %B", "%d %b"):
        try:
            dt = datetime.strptime(dob, fmt)
            return dt.replace(year=1900).strftime("%Y-%m-%d")
        except Exception:
            pass
    log.warning(f"[DOB] Could not parse → {dob!r}")
    return None


def _format_dob_display(dob_norm: str | None) -> str:
    if not dob_norm:
        return "N/A"
    try:
        dt = datetime.strptime(dob_norm, "%Y-%m-%d")
        if dt.year == 1900:
            return dt.strftime("%d-%b")
        return dt.strftime("%d-%b-%Y")
    except Exception:
        return "N/A"


def _create_client_record(name: str, mobile: str, dob: str | None):
    wa = normalize_wa(mobile)
    dob_norm = _normalize_dob(dob)

    with get_session() as s:
        row = s.execute(
            text("SELECT id FROM clients WHERE wa_number=:wa"),
            {"wa": wa},
        ).first()
        if row:
            return row[0]

        r = s.execute(
            text(
                "INSERT INTO clients (name, wa_number, phone, birthday) "
                "VALUES (:n, :wa, :wa, :dob) RETURNING id"
            ),
            {"n": name, "wa": wa, "dob": dob_norm},
        )
        cid = r.scalar()

        s.execute(
            text("UPDATE leads SET status='converted' WHERE wa_number=:wa"),
            {"wa": wa},
        )
        return cid


# ── Webhook ──────────────────────────────────────────────
@router_bp.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
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
            from_wa = msg.get("from")
            text_in = msg.get("text", {}).get("body", "")

            # ─────────────── Interactive ───────────────
            if msg.get("type") == "interactive":
                interactive = msg.get("interactive", {})
                itype = interactive.get("type")

                if itype in {"flow_reply", "nfm_reply"}:
                    try:
                        reply_data = interactive.get(itype, {})
                        params = reply_data.get("response_json", {})
                        if isinstance(params, str):
                            params = json.loads(params)

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

                        if client_name and mobile:
                            _create_client_record(client_name, mobile, dob)
                            dob_display = _format_dob_display(_normalize_dob(dob))
                            msg_out = (
                                "✅ New client registered\n\n"
                                f"Name: {client_name}\n"
                                f"Mobile: {mobile}\n"
                                f"DOB: {dob_display}"
                            )
                            send_whatsapp_text(from_wa, msg_out)
                        else:
                            send_whatsapp_text(
                                from_wa,
                                "⚠️ Client form reply could not be parsed.",
                            )
                        return jsonify({"status": "ok", "role": itype}), 200
                    except Exception as e:
                        log.exception("[Webhook] Failed to handle %s", itype)
                        send_whatsapp_text(
                            from_wa, f"⚠️ Error handling client form: {e}"
                        )
                        return jsonify({"status": "error"}), 200

                elif itype == "button_reply":
                    button = interactive.get("button_reply", {})
                    button_id = button.get("id")
                    btn_key = (button_id or "").lower().replace(" ", "_")

                    # ✅ Handle rejection button
                    if btn_key.startswith("reject_"):
                        sid = btn_key.replace("reject_", "")
                        wa_norm = normalize_wa(from_wa)

                        with get_session() as s:
                            # Update booking status for this client + session
                            s.execute(
                                text("""
                                    UPDATE bookings
                                    SET status='rejected'
                                    WHERE session_id=:sid
                                    AND client_id=(SELECT id FROM clients WHERE wa_number=:wa)
                                """),
                                {"sid": sid, "wa": wa_norm},
                            )

                            # Fetch client + session details
                            row = s.execute(
                                text("""
                                    SELECT c.name, s.session_date, s.start_time
                                    FROM bookings b
                                    JOIN clients c ON b.client_id = c.id
                                    JOIN sessions s ON b.session_id = s.id
                                    WHERE b.session_id=:sid AND c.wa_number=:wa
                                """),
                                {"sid": sid, "wa": wa_norm},
                            ).first()

                            if row:
                                cname, sdate, stime = row
                                session_info = f"{sdate.strftime('%d-%b')} at {stime.strftime('%H:%M')}"
                            else:
                                cname, session_info = "Unknown client", "Unknown time"

                        # Notify client
                        safe_execute(
                            send_whatsapp_text,
                            from_wa,
                            f"❌ Your booking on {session_info} has been cancelled. Nadine has been notified.",
                            label="client_reject_ok"
                        )
                        # Notify Nadine
                        admin_nudge.notify_cancel(
                            cname,
                            wa_norm,
                            f"booking on {session_info} rejected by client"
                        )

                        return jsonify({"status": "ok", "role": "client_reject"}), 200

                    # Other admin button actions
                    handle_admin_action(from_wa, msg.get("id"), None, btn_id=btn_key)
                    return jsonify({"status": "ok", "role": "admin_button"}), 200

            # ─────────────── Button (plain) ───────────────
            if msg.get("type") == "button":
                button = msg.get("button", {})
                button_id = button.get("payload") or button.get("text")
                btn_key = (button_id or "").lower().replace(" ", "_")
                handle_admin_action(from_wa, msg.get("id"), None, btn_id=btn_key)
                return jsonify({"status": "ok", "role": "admin_button"}), 200

            # ─────────────── Text fallback ───────────────
            wa = normalize_wa(from_wa)
            admin_list = os.getenv("ADMIN_WA_LIST", "").split(",")
            if wa in [normalize_wa(x) for x in admin_list if x.strip()]:
                handle_admin_action(wa, msg.get("id"), text_in)
                return jsonify({"status": "ok", "role": "admin"}), 200

            client = _client_get(wa)
            if client:
                send_whatsapp_text(wa, CLIENT_MENU.format(name=client["name"]))
                return jsonify({"status": "ok", "role": "client"}), 200

            start_or_resume(wa, text_in)
            return jsonify({"status": "ok", "role": "prospect"}), 200

        except Exception as e:
            log.exception("[Webhook] Handling failed")
            return jsonify({"status": "error", "error": str(e)}), 500
