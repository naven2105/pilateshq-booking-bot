# app/sessions.py
from __future__ import annotations

from typing import Iterable, List, Literal, Optional, Tuple, Dict, Any
from datetime import date, datetime, time, timedelta
import re

from sqlalchemy import text

from .crud import session_scope

Kind = Literal["single", "duo", "group"]
BookingStatus = Literal["booked", "waitlisted", "cancelled"]

# ──────────────────────────────────────────────────────────────────────────────
# Utilities
# ──────────────────────────────────────────────────────────────────────────────

_WDAY = {
    "mon": 0, "monday": 0,
    "tue": 1, "tues": 1, "tuesday": 1,
    "wed": 2, "wednesday": 2,
    "thu": 3, "thurs": 3, "thursday": 3,
    "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5,
    "sun": 6, "sunday": 6,
}

def parse_time_hhmm(s: str) -> time:
    """
    Accepts '09:00', '9:00', '9', '9am', '09h00', '10h', '10' and returns time(HH:MM).
    """
    t = s.strip().lower()
    # 08h30 / 8h / 8h00
    m = re.fullmatch(r"(\d{1,2})h(\d{2})", t)
    if m:
        return time(int(m.group(1)), int(m.group(2)))
    m = re.fullmatch(r"(\d{1,2})h", t)
    if m:
        return time(int(m.group(1)), 0)
    # 9am / 9:30pm
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", t)
    if m:
        hh = int(m.group(1))
        mm = int(m.group(2) or 0)
        ap = m.group(3)
        if ap == "pm" and hh != 12:
            hh += 12
        if ap == "am" and hh == 12:
            hh = 0
        return time(hh, mm)
    # 09:00
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", t)
    if m:
        return time(int(m.group(1)), int(m.group(2)))
    # 9
    m = re.fullmatch(r"(\d{1,2})", t)
    if m:
        return time(int(m.group(1)), 0)
    raise ValueError(f"Unrecognised time: {s}")

def next_dates_for_weekday(wday: int, *, start_from: date, weeks: int) -> List[date]:
    """
    Returns a list of 'weeks' dates on the given weekday (0=Mon..6=Sun),
    starting on or after start_from.
    """
    if weeks <= 0:
        return []
    delta = (wday - start_from.weekday()) % 7
    first = start_from + timedelta(days=delta)
    return [first + timedelta(weeks=i) for i in range(weeks)]

def seats_for_kind(kind: Kind) -> int:
    return 1 if kind == "single" else (2 if kind == "duo" else 1)  # group seats handled per booking

def default_capacity_for_kind(kind: Kind) -> int:
    if kind == "single":
        return 1
    if kind == "duo":
        return 2
    return 6  # group default cap

# ──────────────────────────────────────────────────────────────────────────────
# Core session helpers
# ──────────────────────────────────────────────────────────────────────────────

def ensure_session(
    session_date: date,
    start_time_obj: time,
    *,
    kind: Kind = "group",
    capacity: Optional[int] = None,
    notes: Optional[str] = None,
) -> int:
    """
    Return session_id for (date, time). Create if missing with provided kind/capacity.
    Your schema: sessions(id, session_date, start_time, capacity, booked_count, status, notes)
    """
    cap = capacity if capacity is not None else default_capacity_for_kind(kind)
    with session_scope() as s:
        row = s.execute(
            text("""
                SELECT id FROM sessions
                WHERE session_date = :d AND start_time = :t
                LIMIT 1
            """),
            {"d": session_date, "t": start_time_obj},
        ).mappings().first()
        if row:
            return int(row["id"])

        # Create
        created = s.execute(
            text("""
                INSERT INTO sessions (session_date, start_time, capacity, booked_count, status, notes)
                VALUES (:d, :t, :cap, 0, 'open', :notes)
                RETURNING id
            """),
            {"d": session_date, "t": start_time_obj, "cap": cap, "notes": notes or kind},
        ).mappings().first()
        return int(created["id"])

def get_session_availability(session_id: int) -> Dict[str, Any]:
    with session_scope() as s:
        row = s.execute(
            text("""
                SELECT id, capacity, booked_count, status, session_date, start_time
                FROM sessions WHERE id = :id
            """),
            {"id": session_id},
        ).mappings().first()
        if not row:
            raise ValueError(f"Session {session_id} not found")
        available = int(row["capacity"]) - int(row["booked_count"])
        return {
            "id": int(row["id"]),
            "capacity": int(row["capacity"]),
            "booked_count": int(row["booked_count"]),
            "available": max(0, available),
            "status": row["status"],
            "session_date": row["session_date"],
            "start_time": row["start_time"],
        }

def _increment_booked_count(session_id: int, seats: int) -> None:
    with session_scope() as s:
        s.execute(
            text("""
                UPDATE sessions
                SET booked_count = booked_count + :seats
                WHERE id = :id
            """),
            {"id": session_id, "seats": seats},
        )

def _decrement_booked_count(session_id: int, seats: int) -> None:
    with session_scope() as s:
        s.execute(
            text("""
                UPDATE sessions
                SET booked_count = GREATEST(0, booked_count - :seats)
                WHERE id = :id
            """),
            {"id": session_id, "seats": seats},
        )

# ──────────────────────────────────────────────────────────────────────────────
# Booking workflows
# ──────────────────────────────────────────────────────────────────────────────

def book_client(
    *,
    client_id: int,
    session_date: date,
    start_time_obj: time,
    kind: Kind,
    seats: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Book a client into a session (creates the session if needed).
    - single → seats=1
    - duo    → seats=2 (use partner_id link via a second booking if you want)
    - group  → seats given or 1 per person
    Returns dict with booking_id/status and session info. Waitlists if full.
    """
    seats_needed = seats if seats is not None else seats_for_kind(kind)
    session_id = ensure_session(session_date, start_time_obj, kind=kind)
    avail = get_session_availability(session_id)

    if avail["status"] != "open":
        # fall back to waitlist
        return _create_waitlist(client_id, session_id, reason="session_closed")

    if avail["available"] >= seats_needed:
        # create booking
        with session_scope() as s:
            booking = s.execute(
                text("""
                    INSERT INTO bookings (client_id, session_id, status, seats)
                    VALUES (:cid, :sid, 'booked', :seats)
                    RETURNING id
                """),
                {"cid": client_id, "sid": session_id, "seats": seats_needed},
            ).mappings().first()
        _increment_booked_count(session_id, seats_needed)
        return {
            "status": "booked",
            "booking_id": int(booking["id"]),
            "session_id": session_id,
            "session": {
                "date": session_date.isoformat(),
                "time": start_time_obj.strftime("%H:%M"),
            },
            "seats": seats_needed,
            "available_after": max(0, avail["available"] - seats_needed),
        }

    # If here, full → waitlist
    return _create_waitlist(client_id, session_id, reason="full")

def cancel_booking(*, booking_id: int) -> Dict[str, Any]:
    """
    Cancels a booking and releases seats back to the session.
    """
    with session_scope() as s:
        row = s.execute(
            text("""
                SELECT b.id, b.session_id, b.status, b.seats
                FROM bookings b
                WHERE b.id = :bid
            """),
            {"bid": booking_id},
        ).mappings().first()
        if not row:
            raise ValueError("Booking not found")

        if row["status"] == "cancelled":
            return {"status": "cancelled", "booking_id": booking_id, "already": True}

        s.execute(
            text("""
                UPDATE bookings
                SET status = 'cancelled'
                WHERE id = :bid
            """),
            {"bid": booking_id},
        )

    _decrement_booked_count(int(row["session_id"]), int(row["seats"]))
    return {"status": "cancelled", "booking_id": booking_id, "released_seats": int(row["seats"])}

def _create_waitlist(client_id: int, session_id: int, *, reason: str) -> Dict[str, Any]:
    with session_scope() as s:
        wl = s.execute(
            text("""
                INSERT INTO waitlist (session_id, client_id)
                VALUES (:sid, :cid)
                RETURNING id
            """),
            {"sid": session_id, "cid": client_id},
        ).mappings().first()
    return {
        "status": "waitlisted",
        "waitlist_id": int(wl["id"]),
        "session_id": session_id,
        "reason": reason,
    }

# ──────────────────────────────────────────────────────────────────────────────
# Recurring booking helpers (e.g., Tue 09h00 and Thu 10h00 for N weeks)
# ──────────────────────────────────────────────────────────────────────────────

def recurring_bookings(
    *,
    client_id: int,
    patterns: Iterable[Tuple[str, str]],  # e.g. [("tue","09h00"), ("thu","10h00")]
    weeks: int = 4,
    kind: Kind = "group",
    seats: Optional[int] = None,
    start_from: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """
    Create bookings for multiple weekday/time patterns over N weeks.
    Returns list of per-occurrence results (booked or waitlisted).
    """
    start_date = start_from or date.today()
    results: List[Dict[str, Any]] = []

    norm_patterns: List[Tuple[int, time]] = []
    for wday_name, tstr in patterns:
        wd = _WDAY.get(wday_name.strip().lower())
        if wd is None:
            raise ValueError(f"Unknown weekday: {wday_name}")
        norm_patterns.append((wd, parse_time_hhmm(tstr)))

    for wd, tm in norm_patterns:
        for d in next_dates_for_weekday(wd, start_from=start_date, weeks=weeks):
            res = book_client(
                client_id=client_id,
                session_date=d,
                start_time_obj=tm,
                kind=kind,
                seats=seats,
            )
            # Attach meta for caller
            res["pattern"] = {"weekday": wd, "time": tm.strftime("%H:%M")}
            results.append(res)

    return results

# ──────────────────────────────────────────────────────────────────────────────
# Lookup helpers (optional convenience)
# ──────────────────────────────────────────────────────────────────────────────

def find_client_by_wa(wa_number: str) -> Optional[int]:
    """
    Convenience helper if admin flow has only WA number.
    """
    from .crud import session_scope as _sc
    from .utils import normalize_wa as _norm

    wa_norm = _norm(wa_number)
    with _sc() as s:
        row = s.execute(
            text("SELECT id FROM clients WHERE wa_number = :wa OR wa_number = :plus LIMIT 1"),
            {"wa": wa_norm, "plus": f"+{wa_norm}"},
        ).mappings().first()
        return int(row["id"]) if row else None

def list_day_sessions(day: date) -> List[Dict[str, Any]]:
    with session_scope() as s:
        rows = s.execute(
            text("""
                SELECT id, session_date, start_time, capacity, booked_count, status, notes
                FROM sessions
                WHERE session_date = :d
                ORDER BY start_time ASC
            """),
            {"d": day},
        ).mappings().all()
    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append({
            "id": int(r["id"]),
            "date": r["session_date"].isoformat(),
            "time": r["start_time"].strftime("%H:%M"),
            "capacity": int(r["capacity"]),
            "booked_count": int(r["booked_count"]),
            "available": max(0, int(r["capacity"]) - int(r["booked_count"])),
            "status": r["status"],
            "notes": r.get("notes"),
        })
    return out
