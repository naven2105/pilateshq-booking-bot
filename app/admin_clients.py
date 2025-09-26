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
from datetime import datetime
from sqlalchemy import text
from .db import get_session
from .utils import send_whatsapp_text, normalize_wa, safe_execute
from . import admin_nudge

log = logging.getLogger(__name__)


def _normalize_dob(dob_raw: str | None) -> str | None:
    """Normalise DOB input into YYYY-MM-DD format or return None."""
    if not dob_raw:
        return None
    s = dob_raw.strip()
    try:
        # Case 1: full date DD-MM-YYYY
        if len(s.split("-")) == 3 and len(s) == 10:
            dt = datetime.strptime(s, "%d-%m-%Y")
            return dt.date().isoformat()
        # Case 2: just DD-MM (no year)
        if len(s.split("-")) == 2:
            dt = datetime.strptime(s, "%d-%m")
            # Default year 1900
            return f"1900-{dt.month:02d}-{dt.day:02d}"
        # Case 3: ISO style YYYY-MM-DD
        if "-" in s and len(s) == 10 and s[4] == "-":
            return s  # assume valid already
    except Exception:
        return None
    return None


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
                    "INSERT INTO clients (name, wa_number, phone) "
                    "VALUES (:n, :wa, :wa) RETURNING id, wa_number"
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
        dob = _normalize_dob(parsed.get("dob"))

        cid, wnum = _find_or_create_client(name, number)
        if cid:
            if dob:
                with get_session() as s:
                    s.execute(
                        text("UPDATE clients SET birthday=:dob WHERE id=:cid"),
                        {"dob": dob, "cid": cid},
                    )
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
        dob = _normalize_dob(parsed.get("dob"))

        cid, wnum = _find_or_create_client(name, parsed.get("number"))
        if not cid:
            safe_execute(
                send_whatsapp_text,
                wa,
                f"⚠ Could not find or create client '{name}'.",
                label="book_client_fail",
            )
            return

        # Store birthday if supplied
        if dob:
            with get_session() as s:
                s.execute(
                    text("UPDATE clients SET birthday=:dob WHERE id=:cid"),
                    {"dob": dob, "cid": cid},
                )

        _mark_lead_converted(wnum, cid)
        _create_booking(cid, session_type, day, time)

        # Admin confirmation
        safe_execute(
            send_whatsapp_text,
            wa,
            f"✅ Booking added for {name} ({session_type}) every {day} at {time}.",
            label="book_client_ok",
        )

        # Notify Nadine (admin nudge)
        admin_nudge.booking_update(
            name=name,
            session_type=session_type,
            day=day,
            time=time,
            dob=dob,
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
        safe_execute(
            send_whatsapp_text,
            wa,
            "❌ Deactivation cancelled. No changes made.",
            label="deactivate_cancel",
        )
        return
