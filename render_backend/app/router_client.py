# render_backend/app/router_client.py
"""
router_client.py – Phase 21
────────────────────────────
Adds:
 • Admin command: “unpaid invoices”
   → Returns list of clients with no or partial payments
 • Client command: “groups” / “group availability”
   → Returns latest group openings from GAS
 • Guest handling gate 🆕
   → Unknown numbers are redirected to Nadine / website
────────────────────────────
"""

import logging, os, requests
from flask import jsonify
from . import client_commands
from .utils import send_whatsapp_text, safe_execute, normalize_wa
from .client_faqs import handle_faq_message, handle_faq_button
from .client_nlp import parse_client_command
from .reschedule_forwarder import forward_reschedule
from .config import NADINE_WA

log = logging.getLogger(__name__)
RENDER_BASE = os.getenv("RENDER_BASE", "https://pilateshq-booking-bot.onrender.com")


# ───────────────────────────────────────────────
# Main Client Handler
# ───────────────────────────────────────────────
def handle_client(msg, wa: str, text_in: str, client: dict):
    """Handle messages from registered clients or admin (Nadine)."""
    txt = (text_in or "").strip()
    msg_type = msg.get("type")
    intent_data = parse_client_command(txt)

    # ── 0️⃣ Guest check – block unregistered numbers ───────────────
    if not client or not client.get("name"):
        safe_execute(
            send_whatsapp_text,
            wa,
            "👋 Welcome to *PilatesHQ Studio!*\n\n"
            "This WhatsApp number is reserved for *registered clients* to manage bookings, reminders, and invoices.\n\n"
            "For enquiries or new sign-ups, please contact *Nadine* on *084 313 1635* "
            "or visit 🌐 *pilateshq.co.za*.",
            label="guest_redirect"
        )
        return jsonify({"status": "ok", "role": "guest_redirect"}), 200

    # ── Handle admin-only commands (Nadine) ────────────────────────
    if normalize_wa(wa) == normalize_wa(NADINE_WA):
        lower_txt = txt.lower()

        # 🔹 On-demand unpaid invoice report
        if lower_txt in ["unpaid invoices", "show unpaid", "unpaid"]:
            try:
                resp = requests.post(f"{RENDER_BASE}/invoices/unpaid", json={})
                if resp.ok:
                    data = resp.json()
                    message = data.get("message", "No response.")
                    safe_execute(send_whatsapp_text, NADINE_WA, f"✅ {message}", label="admin_unpaid_list")
                else:
                    safe_execute(send_whatsapp_text, NADINE_WA,
                                 "⚠️ Could not fetch unpaid invoices.",
                                 label="admin_unpaid_fail")
            except Exception as e:
                log.error(f"[router_client] unpaid invoices fetch failed: {e}")
                safe_execute(send_whatsapp_text, NADINE_WA,
                             f"⚠️ Error fetching unpaid invoices: {e}")
            return jsonify({"status": "ok", "role": "admin_unpaid_invoices"}), 200

    # ── Handle interactive FAQ buttons ─────────────────────────────
    if msg_type == "button":
        button_id = msg.get("button", {}).get("payload")
        if button_id and handle_faq_button(wa, button_id):
            return jsonify({"status": "ok", "role": "client_faq_button"}), 200

    # ── NLP-driven intents for clients ─────────────────────────────
    if intent_data:
        intent = intent_data.get("intent")

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
            forward_reschedule(client.get("name", "Client"), wa)
            safe_execute(send_whatsapp_text, wa,
                         "📅 Thanks! Nadine will assist with rescheduling soon.",
                         label="reschedule_ack")
            safe_execute(send_whatsapp_text, NADINE_WA,
                         f"🔁 *Reschedule Request*\nClient: {client.get('name', 'Unknown')}\nWA: {wa}",
                         label="reschedule_admin_alert")
            return jsonify({"status": "ok", "role": "client_reschedule"}), 200

        # Payment confirmation
        if intent == "payment_confirmation":
            safe_execute(send_whatsapp_text, wa,
                         "💜 Thank you for your payment! Nadine will confirm once received.",
                         label="payment_thanks")
            safe_execute(send_whatsapp_text, NADINE_WA,
                         f"💸 *Payment confirmation received*\nClient: {client.get('name', 'Unknown')}\nWA: {wa}",
                         label="payment_admin_alert")
            return jsonify({"status": "ok", "role": "client_payment_confirmation"}), 200

        # Invoices
        if intent == "get_invoice":
            client_commands.send_invoice(wa)
            return jsonify({"status": "ok", "role": "client_invoice"}), 200

        # 🆕 Group Availability
        if intent == "group_availability":
            try:
                resp = requests.post(
                    f"{RENDER_BASE}/tasks/groups",
                    json={"action": "get_group_availability"},
                    timeout=15
                )
                if resp.ok:
                    data = resp.json()
                    msg = data.get("message", {}).get("message", "⚠️ No group data found.")
                    safe_execute(send_whatsapp_text, wa, msg,
                                 label="client_group_availability")
                else:
                    safe_execute(send_whatsapp_text, wa,
                                 "⚠️ Could not fetch group availability right now.",
                                 label="client_group_availability_fail")
            except Exception as e:
                log.error(f"[router_client] group_availability failed: {e}")
                safe_execute(send_whatsapp_text, wa,
                             f"⚠️ System error fetching availability: {e}",
                             label="client_group_availability_err")
            return jsonify({"status": "ok", "role": "client_group_availability"}), 200

        # FAQs
        if intent == "faq":
            handle_faq_message(wa, txt)
            return jsonify({"status": "ok", "role": "client_faq"}), 200

        # Contact Nadine
        if intent == "contact_admin":
            safe_execute(send_whatsapp_text, wa,
                         "📞 Nadine will reach out to you shortly.",
                         label="client_contact_admin")
            safe_execute(send_whatsapp_text, NADINE_WA,
                         f"📞 *Client wants to contact you*\nName: {client.get('name', 'Unknown')}\nWA: {wa}\nMessage: {txt}",
                         label="admin_contact_alert")
            return jsonify({"status": "ok", "role": "client_contact_admin"}), 200

        # Greeting
        if intent == "greeting":
            name_short = client.get("name", "there").split()[0]
            safe_execute(send_whatsapp_text, wa,
                         f"Hi {name_short} 👋\nHow can I assist today?\nYou can type *bookings*, *faq*, or *groups* to view class availability.",
                         label="client_greeting")
            return jsonify({"status": "ok", "role": "client_greeting"}), 200

    # Default fallback → FAQ menu
    handle_faq_message(wa, "faq")
    return jsonify({"status": "ok", "role": "client_faq_default"}), 200
