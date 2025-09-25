"""
admin_core.py
──────────────
Central dispatcher for admin actions.
Delegates to bookings, clients, and notify modules.
"""

from __future__ import annotations
import logging
from typing import Optional
from .utils import send_whatsapp_text, normalize_wa, safe_execute
from .admin_nlp import parse_admin_command, parse_admin_client_command
from . import admin_bookings, admin_clients

log = logging.getLogger(__name__)


def handle_admin_action(from_wa: str, msg_id: Optional[str], body: str, btn_id: Optional[str] = None):
    """Main entrypoint for inbound admin actions (Nadine / super-admin)."""
    wa = normalize_wa(from_wa)
    text_in = (body or "").strip()

    log.info(f"[ADMIN] from={from_wa} body={body!r} btn_id={btn_id!r}")

    # ─────────────── Menu ───────────────
    if text_in.lower() in {"hi", "menu", "help"}:
        safe_execute(send_whatsapp_text, wa,
            "🛠 Admin Menu\n\n"
            "• Book Sessions → e.g. 'Book Mary on 2025-09-21 08:00 single'\n"
            "• Recurring Sessions → e.g. 'Book Mary every Tuesday 09h00 duo'\n"
            "• Manage Clients → e.g. 'Add client Alice with number 082...'\n"
            "• Attendance Updates → e.g. 'Peter is off sick.'\n"
            "• Deactivate Client → e.g. 'Deactivate Alice'\n"
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

    # ─────────────── Fallback ───────────────
    safe_execute(send_whatsapp_text, wa,
        "⚠ Unknown admin command. Reply 'menu' for options.",
        label="admin_fallback"
    )
