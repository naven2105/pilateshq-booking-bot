#app/client_core.py
"""
client_core.py
──────────────────────────────────────────────
Central dispatcher for client actions.
Delegates to bookings, invoices, attendance, and notify modules.
"""

from __future__ import annotations
import logging
from typing import Optional
from .utils import send_whatsapp_text, normalize_wa, safe_execute
from .client_nlp import parse_client_command
from . import client_bookings, client_attendance, client_faqs
from .invoices import send_invoice
from .prospect import CLIENT_MENU, _client_get
from .config import NADINE_WA

log = logging.getLogger(__name__)


def handle_client_action(from_wa: str, msg_id: Optional[str], body: str):
    """Main entrypoint for inbound client actions (normal clients)."""
    wa = normalize_wa(from_wa)
    text_in = (body or "").strip()
    parsed = parse_client_command(text_in)
    client = _client_get(wa)
    cname = client["name"] if client and client.get("name") else "there"

    log.info(f"[CLIENT] from={from_wa} body={body!r} parsed={parsed}")

    # ─────────────── Greetings → Menu ───────────────
    if text_in.lower() in {"hi", "hello", "hey", "menu"}:
        safe_execute(
            send_whatsapp_text,
            wa,
            CLIENT_MENU.format(name=cname),
            label="client_menu_greeting",
        )
        return

    # ─────────────── Unknown → fallback ───────────────
    if not parsed:
        safe_execute(
            send_whatsapp_text,
            wa,
            f"💜 Hi {cname}, I didn’t quite catch that.\n"
            "Try *bookings*, *faq*, or *message Nadine* for help.",
            label="client_fallback",
        )
        return

    intent = parsed["intent"]
    log.info(f"[CLIENT CMD] intent={intent}")

    # ─────────────── Menu ───────────────
    if intent == "menu":
        safe_execute(
            send_whatsapp_text,
            wa,
            CLIENT_MENU.format(name=cname),
            label="client_menu",
        )
        return

    # ─────────────── Bookings ───────────────
    if intent == "show_bookings":
        client_bookings.show_bookings(wa)
        return

    if intent == "cancel_next":
        client_bookings.cancel_next(wa)
        return

    if intent == "cancel_specific":
        client_bookings.cancel_specific(wa, parsed["day"], parsed["time"])
        return

    # ─────────────── Attendance ───────────────
    if intent == "off_sick_today":
        client_attendance.mark_sick_today(wa)
        return

    if intent == "cancel_today":
        client_attendance.cancel_today(wa)
        return

    if intent == "running_late":
        client_attendance.running_late(wa)
        return

    # ─────────────── Invoices ───────────────
    if intent == "get_invoice":
        safe_execute(send_invoice, wa)
        return

    if intent == "balance":
        safe_execute(
            send_whatsapp_text,
            wa,
            "📊 Your package balance updates will appear here soon.\n"
            "For now, Nadine can confirm your remaining sessions.",
            label="client_balance_redirect",
        )
        return

    # ─────────────── FAQs ───────────────
    if intent == "faq":
        client_faqs.handle_faq_message(wa, "faq")
        return

    # ─────────────── Contact Nadine ───────────────
    if intent == "contact_admin":
        safe_execute(
            send_whatsapp_text,
            wa,
            "📞 Nadine will contact you soon. You can also message her directly at 062 759 7357.",
            label="client_contact_admin",
        )
        safe_execute(
            send_whatsapp_text,
            NADINE_WA,
            f"📩 Client *{cname}* ({wa}) wants to contact you:\n‘{text_in}’",
            label="admin_contact_alert",
        )
        return

    # ─────────────── Unknown fallback (defensive) ───────────────
    safe_execute(
        send_whatsapp_text,
        wa,
        "💬 I’m not sure how to handle that yet — Nadine will follow up shortly.",
        label="client_unknown_fallback",
    )
