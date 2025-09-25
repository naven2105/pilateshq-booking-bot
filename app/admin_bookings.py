"""
admin_bookings.py
─────────────────
Handles booking-related admin commands.
"""

import logging
from sqlalchemy import text
from .db import get_session
from .utils import send_whatsapp_text, safe_execute
from .booking import admin_reserve, create_recurring_bookings, create_multi_recurring_bookings
from .admin_clients import _find_or_create_client, _mark_lead_converted
from .admin_notify import notify_client
from . import admin_nudge

log = logging.getLogger(__name__)


def _find_session(date: str, time: str):
    with get_session() as s:
        row = s.execute(
            text("SELECT id FROM sessions WHERE session_date = :d AND start_time = :t"),
            {"d": date, "t": time},
        ).first()
        return row[0] if row else None


def handle_booking_command(parsed: dict, wa: str):
    """Route parsed booking/admin commands."""

    intent = parsed["intent"]
    log.info(f"[ADMIN BOOKING] parsed={parsed}")

    if intent == "book_single":
        client_id, wnum = _find_or_create_client(parsed["name"], parsed.get("wa_number"))
        if client_id:
            _mark_lead_converted(wnum, client_id)
        sid = _find_session(parsed["date"], parsed["time"])
        if not sid:
            safe_execute(send_whatsapp_text, wa,
                f"⚠ No session found on {parsed['date']} at {parsed['time']}.",
                label="book_single_fail"
            )
            return
        ok = admin_reserve(client_id, sid, 1)
        if ok:
            safe_execute(send_whatsapp_text, wa,
                f"✅ Session booked for {parsed['name']} on {parsed['date']} at {parsed['time']}.",
                label="book_single_ok"
            )
        else:
            safe_execute(send_whatsapp_text, wa,
                "❌ Could not reserve — session is full.",
                label="book_single_full"
            )
        return

    if intent == "book_recurring":
        client_id, wnum = _find_or_create_client(parsed["name"], parsed.get("wa_number"))
        if client_id:
            _mark_lead_converted(wnum, client_id)
        created = create_recurring_bookings(client_id, parsed["weekday"], parsed["time"], parsed["slot_type"])
        safe_execute(send_whatsapp_text, wa,
            f"📅 Created {created} weekly bookings for {parsed['name']} ({parsed['slot_type']}).",
            label="book_recurring"
        )
        return

    if intent == "book_recurring_multi":
        client_id, wnum = _find_or_create_client(parsed["name"], parsed.get("wa_number"))
        if client_id:
            _mark_lead_converted(wnum, client_id)
        created = create_multi_recurring_bookings(client_id, parsed["slots"])
        safe_execute(send_whatsapp_text, wa,
            f"📅 Created {created} recurring bookings for {parsed['name']} across multiple days.",
            label="book_multi"
        )
        return


def cancel_next_booking(name: str, wa: str):
    """Cancel the next booking for a client."""
    with get_session() as s:
        row = s.execute(
            text("""
                SELECT c.id, c.wa_number FROM clients c
                JOIN bookings b ON b.client_id = c.id
                JOIN sessions s ON b.session_id = s.id
                WHERE lower(c.name)=lower(:n) AND b.status='active' AND s.session_date >= CURRENT_DATE
                ORDER BY s.session_date ASC LIMIT 1
            """), {"n": name}).first()

        if not row:
            safe_execute(send_whatsapp_text, wa,
                f"⚠ No active future booking found for {name}.",
                label="cancel_next_none"
            )
            return

        cid, wnum = row
        s.execute(text("UPDATE bookings SET status='cancelled' WHERE client_id=:cid AND id IN "
                       "(SELECT b.id FROM bookings b JOIN sessions s ON b.session_id=s.id "
                       "WHERE s.session_date >= CURRENT_DATE LIMIT 1)"), {"cid": cid})
        notify_client(wnum, "Hi! Your next session has been cancelled by the studio. Please contact us to reschedule 💜")
        safe_execute(send_whatsapp_text, wa,
            f"✅ Next session for {name} cancelled and client notified.",
            label="cancel_next_ok"
        )
        admin_nudge.notify_cancel(name, wnum, "next session")


def mark_today_status(name: str, status: str, wa: str):
    """Mark today’s booking with sick/no-show status."""
    with get_session() as s:
        row = s.execute(
            text("""
                SELECT c.id, c.wa_number FROM clients c
                JOIN bookings b ON b.client_id = c.id
                JOIN sessions s ON b.session_id = s.id
                WHERE lower(c.name)=lower(:n) AND b.status='active' AND s.session_date=CURRENT_DATE
                LIMIT 1
            """), {"n": name}).first()

        if not row:
            safe_execute(send_whatsapp_text, wa,
                f"⚠ No active booking today for {name}.",
                label=f"{status}_none"
            )
            return

        cid, wnum = row
        s.execute(text("UPDATE bookings SET status=:st WHERE client_id=:cid "
                       "AND id IN (SELECT b.id FROM bookings b JOIN sessions s ON b.session_id=s.id "
                       "WHERE s.session_date=CURRENT_DATE LIMIT 1)"),
                  {"st": status, "cid": cid})
        if status == "sick":
            notify_client(wnum, "Hi! We’ve marked you as sick for today’s session. Wishing you a speedy recovery 🌸")
            admin_nudge.notify_sick(name, wnum, "today")
        elif status == "no_show":
            notify_client(wnum, "Hi! You missed today’s session. Please reach out if you’d like to rebook.")
            admin_nudge.notify_no_show(name, wnum, "today")

        safe_execute(send_whatsapp_text, wa,
            f"✅ Marked {name} as {status.replace('_','-')} today and client notified.",
            label=f"{status}_ok"
        )
