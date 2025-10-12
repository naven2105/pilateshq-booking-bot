#app/admin_core.py
"""
admin_core.py
──────────────
Central dispatcher for admin actions.
Delegates to booking, client, and notification modules.
Refactored to remove all DB dependencies.
"""

from __future__ import annotations
import logging
import os
from typing import Optional
from .utils import (
    send_whatsapp_text,
    send_whatsapp_flow,
    normalize_wa,
    safe_execute,
)
from .admin_nlp import parse_admin_command, parse_admin_client_command
from . import admin_bookings

log = logging.getLogger(__name__)

# Flow ID for Add New Client (from Meta → Flows)
CLIENT_REGISTRATION_FLOW_ID = os.getenv("CLIENT_REGISTRATION_FLOW_ID", "24571517685863108")


def handle_admin_action(from_wa: str, body: Optional[str] = None, btn_id: Optional[str] = None):
    """
    Main entry point for inbound admin (Nadine / super-admin) messages.

    Handles:
      - Button actions (e.g., "Add Client")
      - Text commands (bookings, clients, etc.)
      - Admin menu display
      - Fallback unknown responses
    """
    wa = normalize_wa(from_wa)
    text_in = (body or "").strip().lower()
    btn_norm = btn_id.lower().replace(" ", "_") if btn_id else None

    log.info(f"[ADMIN] from={from_wa} body={body!r} btn_id={btn_id!r} → btn_norm={btn_norm}")

    # ─────────────── Handle Button Actions ───────────────
    if btn_norm in {"add_client", "add_client_button"}:
        safe_execute(
            send_whatsapp_flow,
            wa,
            CLIENT_REGISTRATION_FLOW_ID,
            "Add New Client",
            label="admin_add_new_flow_btn",
        )
        return

    # ─────────────── Add Client via Text ───────────────
    if text_in in {"add new", "new client", "add client"}:
        safe_execute(
            send_whatsapp_flow,
            wa,
            CLIENT_REGISTRATION_FLOW_ID,
            "Add New Client",
            label="admin_add_new_flow_text",
        )
        return

    # ─────────────── Admin Menu ───────────────
    if text_in in {"hi", "menu", "help"}:
        safe_execute(
            send_whatsapp_text,
            wa,
            "🛠 *Admin Menu*\n\n"
            "📅 *Bookings*\n"
            "  - Book Mary tomorrow 08h00 single\n"
            "  - Book Peter every Tuesday 09h00 duo\n\n"
            "👥 *Clients*\n"
            "  - Add client Alice with number 082...\n"
            "  - Update DOB Alice 21-May\n"
            "  - Deactivate Alice\n\n"
            "💳 *Attendance*\n"
            "  - Peter sick / cancel / no-show\n\n"
            "💬 Type your command directly or reply 'add new' to register a client.",
            label="admin_menu",
        )
        return

    # ─────────────── Booking Commands ───────────────
    parsed_booking = parse_admin_command(text_in)
    if parsed_booking:
        admin_bookings.handle_booking_command(parsed_booking, wa)
        return

    # ─────────────── Client Commands (deactivate, attendance, etc.) ───────────────
    parsed_client = parse_admin_client_command(text_in)
    if parsed_client:
        # temporarily handled by booking or attendance routing (to be migrated)
        admin_bookings.handle_booking_command(parsed_client, wa)
        return

    # ─────────────── Future invoice / balance placeholders ───────────────
    if text_in.startswith(("invoice ", "balance ")):
        safe_execute(
            send_whatsapp_text,
            wa,
            "🧾 Invoice & balance commands are currently being upgraded for the Google Sheets version.",
            label="admin_invoice_placeholder",
        )
        return

    # ─────────────── Fallback ───────────────
    safe_execute(
        send_whatsapp_text,
        wa,
        "⚠ Unknown admin command. Reply 'menu' for available options.",
        label="admin_fallback",
    )
