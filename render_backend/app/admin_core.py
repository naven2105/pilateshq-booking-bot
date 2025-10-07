"""
admin_core.py
──────────────
Central dispatcher for admin actions.
Delegates to bookings, clients, invoices, and notify modules.
"""

from __future__ import annotations
import logging
from typing import Optional
import os
from .utils import (
    send_whatsapp_text,
    send_whatsapp_flow,
    normalize_wa,
    safe_execute,
)
from .admin_nlp import parse_admin_command, parse_admin_client_command
from . import admin_bookings, admin_clients, admin_invoices

log = logging.getLogger(__name__)

# Flow ID from Meta (published form)
CLIENT_REGISTRATION_FLOW_ID = os.getenv("CLIENT_REGISTRATION_FLOW_ID", "24571517685863108")


def handle_admin_action(from_wa: str, msg_id: Optional[str], body: str, btn_id: Optional[str] = None):
    """Main entrypoint for inbound admin actions (Nadine / super-admin)."""
    wa = normalize_wa(from_wa)
    text_in = (body or "").strip().lower() if body else ""
    btn_norm = btn_id.lower().replace(" ", "_") if btn_id else None

    log.info(f"[ADMIN] from={from_wa} body={body!r} btn_id={btn_id!r} → btn_norm={btn_norm}")

    # ─────────────── Handle Button Actions ───────────────
    if btn_norm in {"add_client", "add_client_button"}:
        safe_execute(
            send_whatsapp_flow,
            wa,
            CLIENT_REGISTRATION_FLOW_ID,
            "Add New Client",
            label="admin_add_new_flow_btn"
        )
        return

    # ─────────────── Add Client via Text ───────────────
    if text_in in {"add new", "new client", "add client"}:
        safe_execute(
            send_whatsapp_flow,
            wa,
            CLIENT_REGISTRATION_FLOW_ID,
            "Add New Client",
            label="admin_add_new_flow_text"
        )
        return

    # ─────────────── Menu ───────────────
    if text_in in {"hi", "menu", "help"}:
        safe_execute(send_whatsapp_text, wa,
            "🛠 Admin Menu\n\n"
            "• Book Sessions → e.g. 'Book Mary tomorrow 08h00 single'\n"
            "• Recurring Sessions → e.g. 'Book Mary every Tuesday 09h00 duo'\n"
            "• Manage Clients → e.g. 'Add client Alice with number 082...'\n"
            "• Update Client → 'update dob Alice 21-May' / 'update mobile Alice 083...'\n"
            "• Add New Client → type 'add new' or tap the Add Client button\n"
            "• Attendance Updates → e.g. 'Peter sick' / 'Peter no-show'\n"
            "• Deactivate Client → e.g. 'Deactivate Alice'\n"
            "• Invoices → 'Invoice John' / 'Balance John'\n"
            "Type your command directly.",
            label="admin_menu"
        )
        return

    # ─────────────── Bookings ───────────────
    parsed = parse_admin_command(text_in)
    if parsed:
        admin_bookings.handle_booking_command(parsed, wa)
        return

    # ─────────────── Clients & Attendance ───────────────
    parsed = parse_admin_client_command(text_in)
    if parsed:
        admin_clients.handle_client_command(parsed, wa)
        return

    # ─────────────── Invoices ───────────────
    if text_in.startswith("invoice "):
        name = text_in.split(" ", 1)[1].strip()
        admin_invoices.send_invoice_admin(name, wa_number=None, month=None, admin_wa=wa)
        return

    if text_in.startswith("balance "):
        name = text_in.split(" ", 1)[1].strip()
        admin_invoices.show_balance_admin(name, wa_number=None, admin_wa=wa)
        return

    # ─────────────── Fallback ───────────────
    safe_execute(send_whatsapp_text, wa,
        "⚠ Unknown admin command. Reply 'menu' for options.",
        label="admin_fallback"
    )
