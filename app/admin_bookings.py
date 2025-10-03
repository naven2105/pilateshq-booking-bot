# app/admin_bookings.py
"""
Handles booking-related admin commands with hybrid client matching:
 - Single-day bookings
 - Recurring bookings
 - Multi-day recurring bookings
 - Cancel next booking
 - Mark sick / no-show today
"""

import logging
from sqlalchemy import text
from datetime import date, timedelta
from .db import get_session
from .utils import send_whatsapp_text, safe_execute, send_whatsapp_button
from .admin_utils import (
    _find_client_matches,
    _confirm_or_disambiguate,
)
from .admin_notify import notify_client
from . import admin_nudge

log = logging.getLogger(__name__)


# ── Helpers ─────────────────────────────────────────────
def normalize_time(t: str) -> str:
    """Convert admin style times like 08h00 → 08:00 for Postgres TIME."""
    if not t:
        return t
    if "h" in t:
        try:
            hh, mm = t.split("h")
            return f"{int(hh):02d}:{int(mm):02d}"
        except Exception:
            pass
    return t  # assume already in HH:MM


def _find_or_create_session(d: str, t: str, slot_type: str) -> int | None:
    """Find existing session or create one with correct capacity."""
    t = normalize_time(t)
    capacity = {"single": 1, "duo": 2, "group": 6}[slot_type]
    with get_session() as s:
        row = s.execute(
            text("SELECT id FROM sessions WHERE session_date=:d AND start_time=:t AND session_type=:ty"),
            {"d": d, "t": t, "ty": slot_type},
        ).first()
        if row:
            return row[0]
        r = s.execute(
            text("""
                INSERT INTO sessions (session_date, start_time, session_type, capacity)
                VALUES (:d, :t, :ty, :cap) RETURNING id
            """),
            {"d": d, "t": t, "ty": slot_type, "cap": capacity},
        )
        return r.scalar()


def _is_session_full(session_id: int) -> bool:
    """Check if session is full by comparing confirmed bookings with capacity."""
    with get_session() as s:
        row = s.execute(
            text("""
                SELECT COUNT(*) AS booked, s.capacity
                FROM sessions s
                LEFT JOIN bookings b ON b.session_id = s.id AND b.status='confirmed'
                WHERE s.id=:sid
                GROUP BY s.capacity
            """), {"sid": session_id}).first()
        if not row:
            return True
        booked, capacity = row
        return booked >= capacity


def _notify_booking(sid, cname, wnum, d, t, slot_type, admin_wa):
    """Notify client of booking with Reject button."""
    msg = (
        f"📅 Nadine booked you for {d} at {t} ({slot_type}).\n\n"
        "If this is incorrect, tap ❌ Reject."
    )
    safe_execute(
        send_whatsapp_button,
        wnum,
        msg,
        buttons=[{"id": f"reject_{sid}", "title": "❌ Reject"}],
        label="client_booking_notify",
    )


# ── Booking Commands ────────────────────────────────────
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

        time_str = normalize_time(parsed["time"])
        sid = _find_or_create_session(parsed["date"], time_str, parsed["slot_type"])
        if _is_session_full(sid):
            safe_execute(send_whatsapp_text, wa,
                "❌ Could not reserve — session is full.",
                label="book_single_full"
            )
            return

        with get_session() as s:
            s.execute(
                text("""
                    INSERT INTO bookings (session_id, client_id, status)
                    VALUES (:sid, :cid, 'confirmed')
                    ON CONFLICT (session_id, client_id) DO NOTHING
                """),
                {"sid": sid, "cid": cid},
            )

        safe_execute(send_whatsapp_text, wa,
            f"✅ Session booked for {cname} on {parsed['date']} at {time_str}.",
            label="book_single_ok"
        )

        _notify_booking(sid, cname, wnum, parsed["date"], time_str, parsed["slot_type"], wa)
        return

    # ── Recurring Booking (weekly) ───────────────────
    if intent == "book_recurring":
        matches = _find_client_matches(parsed["name"])
        choice = _confirm_or_disambiguate(matches, "book recurring", wa)
        if not choice:
            return
        cid, cname, wnum, _ = choice

        weekday = parsed["weekday"].lower()
        slot_time = normalize_time(parsed["time"])
        slot_type = parsed["slot_type"]

        created = 0
        today = date.today()
        for offset in range(0, 8 * 7):  # next 8 weeks
            d = today + timedelta(days=offset)
            if d.strftime("%A").lower() != weekday:
                continue

            sid = _find_or_create_session(d, slot_time, slot_type)
            if _is_session_full(sid):
                continue

            with get_session() as s:
                s.execute(
                    text("""
                        INSERT INTO bookings (session_id, client_id, status)
                        VALUES (:sid, :cid, 'confirmed')
                        ON CONFLICT (session_id, client_id) DO NOTHING
                    """), {"sid": sid, "cid": cid},
                )
            created += 1
            _notify_booking(sid, cname, wnum, d, slot_time, slot_type, wa)

        safe_execute(send_whatsapp_text, wa,
            f"📅 Created {created} weekly bookings for {cname} ({slot_type}).",
            label="book_recurring"
        )
        return

    # ── Multi-day Recurring ──────────────────────────
    if intent == "book_recurring_multi":
        matches = _find_client_matches(parsed["name"])
        choice = _confirm_or_disambiguate(matches, "book recurring multi", wa)
        if not choice:
            return
        cid, cname, wnum, _ = choice

        created = 0
        for slot in parsed["slots"]:   # [{date, time, slot_type}, …]
            d, t, ty = slot["date"], normalize_time(slot["time"]), slot["slot_type"]
            sid = _find_or_create_session(d, t, ty)
            if _is_session_full(sid):
                continue

            with get_session() as s:
                s.execute(
                    text("""
                        INSERT INTO bookings (session_id, client_id, status)
                        VALUES (:sid, :cid, 'confirmed')
                        ON CONFLICT (session_id, client_id) DO NOTHING
                    """), {"sid": sid, "cid": cid},
                )
            created += 1
            _notify_booking(sid, cname, wnum, d, t, ty, wa)

        safe_execute(send_whatsapp_text, wa,
            f"📅 Created {created} recurring bookings for {cname} across multiple days.",
            label="book_multi"
        )
        return


# ── Cancel & Mark Status ───────────────────────────────
def cancel_next_booking(name: str, wa: str):
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
                WHERE b.client_id=:cid AND b.status='confirmed' AND s.session_date >= CURRENT_DATE
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
                WHERE b.client_id=:cid AND b.status='confirmed' AND s.session_date=CURRENT_DATE
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
