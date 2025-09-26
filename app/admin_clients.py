"""
admin_clients.py
────────────────
Handles client management:
 - Add clients
 - Convert leads
 - Book sessions
 - Attendance updates (sick, no-show, cancel next session)
 - Deactivate clients
"""

import logging
from sqlalchemy import text
from .db import get_session
from .utils import send_whatsapp_text, normalize_wa, safe_execute
from . import admin_nudge

log = logging.getLogger(__name__)


def _find_or_create_client(name: str, wa_number: str | None = None):
    """Look up a client by name. If not found and wa_number is given, create."""
    with get_session() as s:
        row = s.execute(
            text("SELECT id, wa_number FROM clients WHERE lower(name)=lower(:n)"),
            {"n": name},
        ).first()
        if row:
            return row[0], row[1]
        if wa_number:
            r = s.execute(
                text(
                    "INSERT INTO clients (name, wa_number, phone, package_type) "
                    "VALUES (:n, :wa, :wa, 'manual') RETURNING id, wa_number"
                ),
                {"n": name, "wa": wa_number},
            )
            return r.first()
    return None, None


def _mark_lead_converted(wa_number: str, client_id: int):
    """Mark a lead as converted once promoted to client."""
    with get_session() as s:
        s.execute(
            text("UPDATE leads SET status='converted' WHERE wa_number=:wa"),
            {"wa": wa_number},
        )
    log.info(f"Lead {wa_number} promoted → client {client_id}")


def _create_booking(client_id: int, session_type: str, day: str, time: str):
    """Insert a new recurring booking into the bookings table."""
    with get_session() as s:
        s.execute(
            text(
                "INSERT INTO bookings (client_id, session_type, day_of_week, time_of_day, status) "
                "VALUES (:cid, :stype, :day, :time, 'booked')"
            ),
            {"cid": client_id, "stype": session_type, "day": day, "time": time},
        )
    log.info(f"Booking created for client={client_id} type={session_type} {day} {time}")


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
        cid, wnum = _find_or_create_client(name, number)
        if cid:
            _mark_lead_converted(wnum, cid)
            safe_execute(
                send_whatsapp_text,
                wa,
                f"✅ Client '{name}' added with number {wnum}.",
                label="add_client_ok",
            )
        else:
            safe_execute(
                send_whatsapp_text,
                wa,
                f"⚠ Could not add client '{name}'.",
                label="add_client_fail",
            )
        return

    # ── Book Client ──
    if intent == "book_client":
        name = parsed["name"]
        session_type = parsed.get("session_type", "group")
        day = parsed.get("day", "Tue")
        time = parsed.get("time", "08h00")
        dob = parsed.get("dob")
        health = parsed.get("health")

        cid, wnum = _find_or_create_client(name, parsed.get("number"))
        if not cid:
            safe_execute(
                send_whatsapp_text,
                wa,
                f"⚠ Could not find or create client '{name}'.",
                label="book_client_fail",
            )
            return

        # Store birthday / health if supplied
        if dob or health:
            with get_session() as s:
                s.execute(
                    text("UPDATE clients SET birthday=:dob, health_info=:health WHERE id=:cid"),
                    {"dob": dob, "health": health, "cid": cid},
                )

        _mark_lead_converted(wnum, cid)
        _create_booking(cid, session_type, day, time)

        # Admin confirmation (back to Nadine)
        safe_execute(
            send_whatsapp_text,
            wa,
            f"✅ Booking added for {name} ({session_type}) every {day} at {time}.",
            label="book_client_ok",
        )

        # Notify Nadine with booking details
        admin_nudge.booking_update(
            name=name,
            session_type=session_type,
            day=day,
            time=time,
            dob=dob,
            health=health,
        )

        # Notify client directly
        safe_execute(
            send_whatsapp_text,
            wnum,  # client WA number
            f"💜 Hi {name}, thanks for booking with PilatesHQ!\n"
            f"Your {session_type.title()} session is reserved:\n"
            f"📅 Every {day} at {time}.\n\n"
            "We look forward to seeing you!",
            label="client_booking_confirm",
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
        from .admin_bookings import mark_
