"""
client_core.py
──────────────────────────────────────────────
Central dispatcher for client actions.
Now delegates menu display to utils.trigger_client_menu().
──────────────────────────────────────────────
"""

from __future__ import annotations
import logging
from typing import Optional
from .utils import (
    send_whatsapp_text,
    normalize_wa,
    safe_execute,
    trigger_client_menu,
)
from . import client_bookings, client_attendance
from .invoices import send_invoice
from .client_reschedule_handler import handle_reschedule_event
from .config import NADINE_WA

log = logging.getLogger(__name__)


def handle_client_action(from_wa: str, msg_id: Optional[str], body: str):
    """Main entrypoint for inbound client actions (normal clients)."""
    wa = normalize_wa(from_wa)
    text_in = (body or "").strip().lower()
    cname = "there"

    log.info(f"[CLIENT] from={from_wa} body={body!r}")

    # ─────────────── Greetings → Menu ───────────────
    if text_in in {"hi", "hello", "hey", "menu", "help"}:
        log.info(f"[CLIENT MENU] Triggering template menu for {wa}")
        safe_execute("menu_template", trigger_client_menu, wa, cname)
        return

    # ─────────────── Booking Commands ───────────────
    if "bookings" in text_in or "my schedule" in text_in:
        client_bookings.show_bookings(wa)
        return

    if "cancel next" in text_in:
        client_bookings.cancel_next(wa)
        return

    if "cancel today" in text_in:
        client_attendance.cancel_today(wa)
        return

    if "sick" in text_in:
        client_attendance.mark_sick_today(wa)
        return

    if "late" in text_in or "running late" in text_in:
        client_attendance.running_late(wa)
        return

    # ─────────────── Reschedule ───────────────
    if "reschedule" in text_in:
        handle_reschedule_event(cname, wa, body)
        return

    # ─────────────── Invoice / Balance ───────────────
    if "invoice" in text_in:
        safe_execute("invoice_send", send_invoice, wa)
        return

    if "balance" in text_in:
        safe_execute(
            "balance_info",
            send_whatsapp_text,
            wa,
            "📊 Your package balance updates will appear here soon.\n"
            "For now, Nadine can confirm your remaining sessions.",
        )
        return

    # ─────────────── Contact Nadine ───────────────
    if "contact" in text_in or "nadine" in text_in:
        safe_execute(
            "contact_admin_client",
            send_whatsapp_text,
            wa,
            "📞 Nadine will contact you soon. You can also message her directly at 062 759 7357.",
        )
        safe_execute(
            "contact_admin_alert",
            send_whatsapp_text,
            NADINE_WA,
            f"📩 Client ({wa}) wants to contact you:\n‘{body}’",
        )
        return

    # ─────────────── Unknown fallback ───────────────
    safe_execute(
        "client_unknown_fallback",
        send_whatsapp_text,
        wa,
        "💬 I’m not sure how to handle that yet — Nadine will follow up shortly.",
    )
