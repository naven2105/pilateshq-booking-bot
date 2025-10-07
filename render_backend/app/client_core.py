"""
client_core.py
──────────────
Central dispatcher for client actions.
Delegates to bookings, invoices, attendance, and notify modules.
"""

from __future__ import annotations
import logging
from typing import Optional
from .utils import send_whatsapp_text, normalize_wa, safe_execute
from .client_nlp import parse_client_command
from . import client_bookings, client_attendance
from .prospect import CLIENT_MENU, _client_get  # ✅ reuse client lookup + menu

log = logging.getLogger(__name__)


def handle_client_action(from_wa: str, msg_id: Optional[str], body: str):
    """Main entrypoint for inbound client actions (normal clients)."""
    wa = normalize_wa(from_wa)
    text_in = (body or "").strip()

    log.info(f"[CLIENT] from={from_wa} body={body!r}")

    # ─────────────── Shortcut: greetings → show menu ───────────────
    if text_in.lower() in {"hi", "hello", "hey"}:
        client = _client_get(wa)
        cname = client["name"] if client else "there"
        safe_execute(
            send_whatsapp_text,
            wa,
            CLIENT_MENU.format(name=cname),
            label="client_menu_greeting",
        )
        return

    parsed = parse_client_command(text_in)
    if not parsed:
        # ✅ Fallback now greets by name if available
        client = _client_get(wa)
        cname = client["name"] if client else "there"
        safe_execute(
            send_whatsapp_text,
            wa,
            f"💜 Hi {cname}, I didn’t understand that.\n"
            "Type *menu* to see what I can do for you.",
            label="client_fallback",
        )
        return

    intent = parsed["intent"]
    log.info(f"[CLIENT CMD] parsed={parsed}")

    # ─────────────── Menu ───────────────
    if intent == "menu":
        client = _client_get(wa)
        cname = client["name"] if client else "there"
        safe_execute(
            send_whatsapp_text,
            wa,
            CLIENT_MENU.format(name=cname),
            label="client_menu",
        )
        return

    # ─────────────── View Bookings ───────────────
    if intent == "show_bookings":
        client_bookings.show_bookings(wa)
        return

    # ─────────────── Cancel Next ───────────────
    if intent == "cancel_next":
        client_bookings.cancel_next(wa)
        return

    # ─────────────── Cancel Specific ───────────────
    if intent == "cancel_specific":
        client_bookings.cancel_specific(wa, parsed["day"], parsed["time"])
        return

    # ─────────────── Attendance Updates ───────────────
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
        safe_execute(
            send_whatsapp_text,
            wa,
            "📑 Invoices are currently managed directly by Nadine. Please contact her if you need a copy.",
            label="client_invoice_redirect",
        )
        return

    if intent == "balance":
        safe_execute(
            send_whatsapp_text,
            wa,
            "📊 Balance requests are not yet automated. Please contact Nadine for details.",
            label="client_balance_redirect",
        )
        return

    # ─────────────── FAQs ───────────────
    if intent == "faq":
        safe_execute(
            send_whatsapp_text,
            wa,
            "ℹ PilatesHQ Info:\n\n"
            "• Reformer Single = R300\n"
            "• Reformer Duo = R250\n"
            "• Reformer Trio = R200\n\n"
            "Type 'sessions' to view your bookings or 'invoice' to get your statement.",
            label="client_faq",
        )
        return

    # ─────────────── Contact Nadine ───────────────
    if intent == "contact_admin":
        safe_execute(
            send_whatsapp_text,
            wa,
            "📞 You can reach Nadine directly at: 0627597357",
            label="client_contact_admin",
        )
        return
