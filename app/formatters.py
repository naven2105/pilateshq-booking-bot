# app/formatters.py
from __future__ import annotations

from datetime import date, time
from typing import List, Optional, Tuple

# ── Client messages ───────────────────────────────────────────────────────────

def _fmt(d: date, t: time) -> str:
    return f"{d.strftime('%a %d %b')} at {t.strftime('%H:%M')}"

def format_next_lesson(result: Optional[Tuple[date, time]]) -> str:
    if not result:
        return "You have no upcoming sessions. Reply BOOK to schedule one."
    d, t = result
    return f"Your next lesson is {_fmt(d, t)}."

def format_sessions_this_week(rows: List[Tuple[date, time]]) -> str:
    if not rows:
        return "You have no sessions in the next 7 days."
    items = [f"- {_fmt(d, t)}" for d, t in rows]
    return "Your sessions this week:\n" + "\n".join(items)

def format_weekly_schedule(rows: List[Tuple[date, time, str]]) -> str:
    if not rows:
        return "No sessions scheduled in the next 7 days."
    items = [f"- {d.strftime('%a %d %b')} {t.strftime('%H:%M')} — {name}" for d, t, name in rows]
    return "Upcoming week:\n" + "\n".join(items)

# ── Admin messages ────────────────────────────────────────────────────────────

def format_client_sessions(rows: List[Tuple[date, time]], client_name: str) -> str:
    if not rows:
        return f"No upcoming sessions found for '{client_name}'."
    items = [f"- {_fmt(d, t)}" for d, t in rows]
    return f"Sessions for {client_name}:\n" + "\n".join(items)

def format_clients_for_time(names: List[str], hhmm: str, date_str: str) -> str:
    if not names:
        return f"No clients booked for {date_str} at {hhmm}."
    return f"Clients at {date_str} {hhmm}: " + ", ".join(names)

def format_clients_today(rows: List[Tuple[time, str]]) -> str:
    if not rows:
        return "No clients booked today."
    items = [f"- {t.strftime('%H:%M')} — {name}" for t, name in rows]
    return "Today’s clients:\n" + "\n".join(items)

def format_cancellations(rows: List[Tuple[time, str]]) -> str:
    if not rows:
        return "No cancellations today."
    items = [f"- {t.strftime('%H:%M')} — {name}" for t, name in rows]
    return "Cancellations today:\n" + "\n".join(items)

# ── Info messages ─────────────────────────────────────────────────────────────

def format_today_date(s: str) -> str:
    return f"Today is {s}."

def format_current_time(s: str) -> str:
    return f"The current time is {s}."

def format_studio_address(s: str) -> str:
    return f"Our studio address is: {s}"

def format_studio_rules(s: str) -> str:
    return f"Studio rules: {s}"
