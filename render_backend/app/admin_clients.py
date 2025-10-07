"""
admin_clients.py
────────────────
Handles client management:
 - Add clients
 - Convert leads
 - Attendance updates (sick, no-show, cancel next session)
 - Deactivate clients
"""

import logging
from sqlalchemy import text
from .db import get_session
from .utils import send_whatsapp_text, normalize_wa, safe_execute
from .admin_notify import notify_client, notify_admin
from . import admin_nudge

log = logging.getLogger(__name__)


def _find_or_create_client(name: str, wa_number: str | None = None):
    """Look up a client by name. If not found and wa_number is given, create."""
    wa_number = normalize_wa(wa_number) if wa_number else None

    with get_session() as s:
        # Try to find an existing client by name or number
        row = s.execute(
            text("SELECT id, wa_number FROM clients WHERE lower(name)=lower(:n) OR wa_number=:wa"),
            {"n": name, "wa": wa_number},
        ).first()
        if row:
            log.info(f"[CLIENT EXISTS] name={name}, wa={wa_number}, id={row[0]}")
            return row[0], row[1], True  # ✅ already exists

        # If not found and wa_number provided → create
        if wa_number:
            r = s.execute(
                text("INSERT INTO clients (name, wa_number, phone) "
                     "VALUES (:n, :wa, :wa) RETURNING id, wa_number"),
                {"n": name, "wa": wa_number},
            )
            return r.first()[0], wa_number, False  # ✅ new created

    return None, None, False


def _mark_lead_converted(wa_number: str, client_id: int):
    """Mark a lead as converted once promoted to client."""
    with get_session() as s:
        s.execute(
            text("UPDATE leads SET status='converted' WHERE wa_number=:wa"),
            {"wa": wa_number},
        )
    log.info(f"Lead {wa_number} promoted → client {client_id}")


def handle_client_command(parsed: dict, wa: str):
    """Route parsed client/admin commands."""

    intent = parsed["intent"]
    log.info(f"[ADMIN CLIENT] parsed={parsed}")

    # ── Add Client ──
    if intent == "add_client":
        name = parsed["name"]
        number = parsed["number"].replace("+", "")
        if number.startswith("0"):
            number = "27" + number[1:]

        cid, wnum, existed = _find_or_create_client(name, number)
        if cid:
            if existed:
                safe_execute(send_whatsapp_text, wa,
                    f"ℹ Client '{name}' already exists with number {wnum}.",
                    label="add_client_exists"
                )
            else:
                _mark_lead_converted(wnum, cid)
                safe_execute(send_whatsapp_text, wa,
                    f"✅ Client '{name}' added with number {wnum}.",
                    label="add_client_ok"
                )
                # Send welcome to client
                safe_execute(send_whatsapp_text, wnum,
                    f"💜 Hi {name}, you’ve been added as a PilatesHQ client. "
                    f"Nadine will confirm your bookings with you soon!",
                    label="client_welcome"
                )
        else:
            safe_execute(send_whatsapp_text, wa,
                f"⚠ Could not add client '{name}'.",
                label="add_client_fail"
            )
        return

    # ── Cancel Next ──
    if intent == "cancel_next":
        from .admin_bookings import cancel_next_booking
        cancel_next_booking(parsed["name"], wa)
        return

    # ── Sick Today ──
    if intent == "off_sick_today":
        from .admin_bookings import mark_today_status
        mark_today_status(parsed["name"], "sick", wa)
        return

    # ── No-show ──
    if intent == "no_show_today":
        from .admin_bookings import mark_today_status
        mark_today_status(parsed["name"], "no_show", wa)
        return

    # ── Deactivation ──
    if intent == "deactivate":
        admin_nudge.request_deactivate(parsed["name"], wa)
        return

    if intent == "confirm_deactivate":
        admin_nudge.confirm_deactivate(parsed["name"], wa)
        return

    if intent == "cancel":
        safe_execute(send_whatsapp_text, wa,
            "❌ Deactivation cancelled. No changes made.",
            label="deactivate_cancel"
        )
        return
