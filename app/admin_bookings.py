"""
admin_bookings.py
─────────────────
Handles booking-related admin commands with hybrid client matching:
 - Single-day bookings
 - Recurring bookings
 - Multi-day recurring bookings
 - Cancel next booking
 - Mark sick / no-show today
"""

import logging
from sqlalchemy import text
from .db import get_session
from .utils import send_whatsapp_text, send_whatsapp_buttons, safe_execute
from .booking import admin_reserve, create_recurring_bookings, create_multi_recurring_bookings
from .admin_utils import (
    _find_or_create_client,
    _find_client_matches,
    _confirm_or_disambiguate,
)
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

    # ── Single Booking ───────────────────────────────
    if intent == "book_single":
        matches = _find_client_matches(parsed["name"])
        choice = _confirm_or_disambiguate(matches, "book session", wa)
        if not choice:
            return
        cid, cname, wnum, _ = choice

        sid = _find_session(parsed["date"], parsed["time"])
        if not sid:
            safe_execute(send_whatsapp_text, wa,
                f"⚠ No session found on {parsed['date']} at {parsed['time']}.",
                label="book_single_fail"
            )
            return

        # ✅ Book with confirmed status
        ok = admin_reserve(cid, sid, 1, status="confirmed")
        if ok:
            # Notify Nadine
            safe_execute(send_whatsapp_text, wa,
                f"✅ Session booked for {cname} on {parsed['date']} at {parsed['time']}.",
                label="book_single_ok"
            )

            # Notify client with reject option
            msg = (
                f"📅 Nadine booked you for {parsed['date']} at {parsed['time']} "
                f"({parsed.get('slot_type') or 'session'}).\n\n"
                "If this is incorrect, tap ❌ Reject."
            )
            safe_execute(
                send_whatsapp_buttons,
                wnum,
                msg,
                buttons=[{"id": f"reject_{sid}", "title": "❌ Reject"}],
                label="client_booking_notify",
            )

        else:
            safe_execute(send_whatsapp_text, wa,
                "❌ Could not reserve — session is full.",
                label="book_single_full"
            )
        return

    # ── Recurring Booking ────────────────────────────
    if intent == "book_recurring":
        matches = _find_client_matches(parsed["name"])
        choice = _confirm_or_disambiguate(matches, "book recurring", wa)
        if not choice:
            return
        cid, cname, _, _ = choice

        created = create_recurring_bookings(
            cid, parsed["weekday"], parsed["time"], parsed["slot_type"]
        )
        safe_execute(send_whatsapp_text, wa,
            f"📅 Created {created} weekly bookings for {cname} ({parsed['slot_type']}).",
            label="book_recurring"
        )
        return

    # ── Multi-day Recurring ──────────────────────────
    if intent == "book_recurring_multi":
        matches = _find_client_matches(parsed["name"])
        choice = _confirm_or_disambiguate(matches, "book recurring multi", wa)
        if not choice:
            return
        cid, cname, _, _ = choice

        created = create_multi_recurring_bookings(cid, parsed["slots"])
        safe_execute(send_whatsapp_text, wa,
            f"📅 Created {created} recurring bookings for {cname} across multiple days.",
            label="book_multi"
        )
        return


def cancel_next_booking(name: str, wa: str):
    """Cancel the next booking for a client with hybrid matching."""
    matches = _find_client_matches(name)
    choice = _confirm_or_disambiguate(matches, "cancel next booking", wa)
    if not choice:
        return
    cid, cname, wnum, _ = choice

    with get_session() as s:
        row = s.execute(
            text("""
                SELECT b.id FROM bookings b
                JOIN sessions s ON b.session_id = s.id
                WHERE b.client_id=:cid AND b.status='active' AND s.session_date >= CURRENT_DATE
                ORDER BY s.session_date ASC LIMIT 1
            """), {"cid": cid}).first()

        if not row:
            safe_execute(send_whatsapp_text, wa,
                f"⚠ No active future booking found for {cname}.",
                label="cancel_next_none"
            )
            return

        bid = row[0]
        s.execute(text("UPDATE bookings SET status='cancelled' WHERE id=:bid"), {"bid": bid})

    notify_client(wnum, "Hi! Your next session has been cancelled by the studio. Please contact us to reschedule 💜")
    safe_execute(send_whatsapp_text, wa,
        f"✅ Next session for {cname} cancelled and client notified.",
        label="cancel_next_ok"
    )
    admin_nudge.notify_cancel(cname, wnum, "next session")


def mark_today_status(name: str, status: str, wa: str):
    """Mark today’s booking with sick/no-show status, with hybrid matching."""
    matches = _find_client_matches(name)
    choice = _confirm_or_disambiguate(matches, f"mark {status}", wa)
    if not choice:
        return
    cid, cname, wnum, _ = choice

    with get_session() as s:
        row = s.execute(
            text("""
                SELECT b.id FROM bookings b
                JOIN sessions s ON b.session_id = s.id
                WHERE b.client_id=:cid AND b.status='active' AND s.session_date=CURRENT_DATE
                LIMIT 1
            """), {"cid": cid}).first()

        if not row:
            safe_execute(send_whatsapp_text, wa,
                f"⚠ No active booking today for {cname}.",
                label=f"{status}_none"
            )
            return

        bid = row[0]
        s.execute(text("UPDATE bookings SET status=:st WHERE id=:bid"),
                  {"st": status, "bid": bid})

    if status == "sick":
        notify_client(wnum, "Hi! We’ve marked you as sick for today’s session. Wishing you a speedy recovery 🌸")
        admin_nudge.notify_sick(cname, wnum, "today")
    elif status == "no_show":
        notify_client(wnum, "Hi! You missed today’s session. Please reach out if you’d like to rebook.")
        admin_nudge.notify_no_show(cname, wnum, "today")

    safe_execute(send_whatsapp_text, wa,
        f"✅ Marked {cname} as {status.replace('_','-')} today and client notified.",
        label=f"{status}_ok"
    )
