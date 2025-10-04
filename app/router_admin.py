# app/router_admin.py
"""
router_admin.py
────────────────
Handles admin messages, interactive replies, and buttons.
Delegates to admin_core, admin_bookings, etc.
"""

import logging
import json
from flask import jsonify
from sqlalchemy import text
from .admin_core import handle_admin_action
from .db import get_session
from .utils import normalize_wa, send_whatsapp_text, safe_execute
from . import admin_nudge
from .router_helpers import _create_client_record, _normalize_dob, _format_dob_display

log = logging.getLogger(__name__)


def handle_admin(msg, wa: str, text_in: str):
    """Handle admin plain text messages."""
    handle_admin_action(wa, msg.get("id"), text_in)
    return jsonify({"status": "ok", "role": "admin"}), 200


def handle_button(msg, wa: str):
    """Handle plain WhatsApp button clicks for admin flows."""
    button = msg.get("button", {})
    button_id = button.get("payload") or button.get("text")
    btn_key = (button_id or "").lower().replace(" ", "_")
    handle_admin_action(wa, msg.get("id"), None, btn_id=btn_key)
    return jsonify({"status": "ok", "role": "admin_button"}), 200


def handle_interactive(msg, wa: str):
    """Handle interactive replies: flows, nfm, or button_reply."""
    interactive = msg.get("interactive", {})
    itype = interactive.get("type")

    # ── Client Registration Flow ──
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

                # ✅ Notify Nadine
                admin_nudge.booking_update(
                    client_name, "New Client", "N/A", "N/A", dob=dob
                )

                # ✅ Notify Admin (the sender, Nadine)
                msg_out = (
                    "✅ New client registered\n\n"
                    f"Name: {client_name}\n"
                    f"Mobile: {mobile}\n"
                    f"DOB: {dob_display}"
                )
                safe_execute(send_whatsapp_text, wa, msg_out, label="admin_flow_client_added")

                # ✅ Notify Client
                safe_execute(
                    send_whatsapp_text,
                    normalize_wa(mobile),
                    f"💜 Hi {client_name}, you’ve been registered with PilatesHQ.\n"
                    f"We look forward to seeing you in class!",
                    label="client_registration_ok",
                )
            else:
                safe_execute(
                    send_whatsapp_text,
                    wa,
                    "⚠️ Client form reply could not be parsed. Missing name or mobile.",
                    label="admin_flow_client_fail",
                )

            return jsonify({"status": "ok", "role": itype}), 200

        except Exception as e:
            log.exception("[ADMIN FLOW] Failed: %s", e)
            safe_execute(send_whatsapp_text, wa, f"⚠ Error handling form: {e}")
            return jsonify({"status": "error"}), 200

    # ── Client Reject Button ──
    elif itype == "button_reply":
        button = interactive.get("button_reply", {})
        button_id = (button.get("id") or "").lower()

        if button_id.startswith("reject_"):
            sid = button_id.replace("reject_", "")
            wa_norm = normalize_wa(wa)

            with get_session() as s:
                # Mark booking rejected
                s.execute(
                    text("""
                        UPDATE bookings
                        SET status='rejected'
                        WHERE session_id=:sid
                        AND client_id=(SELECT id FROM clients WHERE wa_number=:wa)
                    """),
                    {"sid": sid, "wa": wa_norm},
                )

                # Get details for notification
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
                wa_norm,
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

        # Otherwise → treat as admin button
        btn_key = button_id.replace(" ", "_")
        handle_admin_action(wa, msg.get("id"), None, btn_id=btn_key)
        return jsonify({"status": "ok", "role": "admin_button"}), 200

    return jsonify({"status": "ignored"}), 200
