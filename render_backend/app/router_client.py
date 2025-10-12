"""
router_client.py
────────────────
Handles client messages (non-admin).
Delegates to client_commands (bookings, cancel, message Nadine).
Now defaults to the interactive FAQ menu for unrecognised messages.
"""

import logging
from flask import jsonify
from . import client_commands
from .utils import send_whatsapp_text, safe_execute
from .db import get_session
from sqlalchemy import text
from .client_faqs import handle_faq_message, handle_faq_button
from .client_nlp import parse_client_command
from .reschedule_forwarder import forward_reschedule
from .config import NADINE_WA

log = logging.getLogger(__name__)


def client_get(wa: str):
    """Fetch client record by WhatsApp number."""
    with get_session() as s:
        row = s.execute(
            text("SELECT id, name FROM clients WHERE wa_number=:wa"),
            {"wa": wa},
        ).first()
        if row:
            return {"id": row[0], "name": row[1]}
        return None


def handle_client(msg, wa: str, text_in: str, client: dict):
    """Handle messages from registered clients."""
    txt = text_in.strip()
    msg_type = msg.get("type")
    intent_data = parse_client_command(txt)

    # ── Handle interactive FAQ buttons
    if msg_type == "button":
        button_id = msg["button"]["payload"]
        if handle_faq_button(wa, button_id):
            return jsonify({"status": "ok", "role": "client_faq_button"}), 200

    # ── NLP-driven intents
    if intent_data:
        intent = intent_data.get("intent")

        # Bookings
        if intent == "show_bookings":
            client_commands.show_bookings(wa)
            return jsonify({"status": "ok", "role": "client_bookings"}), 200

        if intent == "cancel_next":
            client_commands.cancel_next(wa)
            return jsonify({"status": "ok", "role": "client_cancel_next"}), 200

        if intent == "cancel_specific":
            day = intent_data.get("day")
            time = intent_data.get("time")
            client_commands.cancel_specific(wa, day, time)
            return jsonify({"status": "ok", "role": "client_cancel_specific"}), 200

        # Attendance
        if intent in {"off_sick_today", "cancel_today", "running_late"}:
            client_commands.handle_attendance(wa, intent)
            return jsonify({"status": "ok", "role": f"client_{intent}"}), 200

        # Reschedule
        if intent == "reschedule_request":
            forward_reschedule(client["name"], wa)
            safe_execute(
                send_whatsapp_text,
                wa,
                "📅 Thanks! Nadine will assist with rescheduling soon.",
                label="reschedule_ack"
            )
            safe_execute(
                send_whatsapp_text,
                NADINE_WA,
                f"🔁 *Reschedule Request*\nClient: {client['name']}\nWA: {wa}",
                label="reschedule_admin_alert"
            )
            return jsonify({"status": "ok", "role": "client_reschedule"}), 200

        # Payment confirmation
        if intent == "payment_confirmation":
            safe_execute(
                send_whatsapp_text,
                wa,
                "💜 Thank you for your payment! Nadine will confirm once received.",
                label="payment_thanks"
            )
            safe_execute(
                send_whatsapp_text,
                NADINE_WA,
                f"💸 *Payment confirmation received*\nClient: {client['name']}\nWA: {wa}",
                label="payment_admin_alert"
            )
            return jsonify({"status": "ok", "role": "client_payment_confirmation"}), 200

        # Invoices
        if intent == "get_invoice":
            client_commands.send_invoice(wa)
            return jsonify({"status": "ok", "role": "client_invoice"}), 200

        # FAQs
        if intent == "faq":
            handle_faq_message(wa, txt)
            return jsonify({"status": "ok", "role": "client_faq"}), 200

        # Contact Nadine
        if intent == "contact_admin":
            safe_execute(
                send_whatsapp_text,
                wa,
                "📞 Nadine will reach out to you shortly. You can also message her directly here.",
                label="client_contact_admin"
            )
            safe_execute(
                send_whatsapp_text,
                NADINE_WA,
                f"📞 *Client wants to contact you*\nName: {client['name']}\nWA: {wa}\nMessage: {txt}",
                label="admin_contact_alert"
            )
            return jsonify({"status": "ok", "role": "client_contact_admin"}), 200

        # Greeting → polite default
        if intent == "greeting":
            safe_execute(
                send_whatsapp_text,
                wa,
                f"Hi {client['name'].split()[0]} 👋\nHow can I assist today?\nYou can type *bookings*, *faq*, or *message Nadine*.",
                label="client_greeting"
            )
            return jsonify({"status": "ok", "role": "client_greeting"}), 200

    # ── Default fallback → show FAQ
    handle_faq_message(wa, "faq")
    return jsonify({"status": "ok", "role": "client_faq_default"}), 200
