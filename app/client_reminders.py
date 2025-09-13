# app/client_reminders.py
from __future__ import annotations
import logging
from sqlalchemy import text
from datetime import timedelta
from .db import get_session
from .utils import normalize_wa
from .templates import send_whatsapp_template
from .config import TZ_NAME
from . import crud

# ─────────────────────────────────────────────
# SQL helpers
# ─────────────────────────────────────────────

def _sessions_for_offset(days_ahead: int) -> list[dict]:
    """
    Return sessions X days ahead (e.g. tomorrow = 1).
    """
    sql = """
        WITH base AS (
            SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz)::date AS today
        )
        SELECT s.id, s.session_date, s.start_time, s.capacity,
               s.booked_count, s.status,
               COALESCE((
                   SELECT STRING_AGG(c2.wa_number, ',')
                   FROM bookings b2
                   JOIN clients c2 ON c2.id = b2.client_id
                   WHERE b2.session_id = s.id
                     AND b2.status = 'confirmed'
               ), '') AS wa_numbers
        FROM sessions s, base
        WHERE s.session_date = base.today + :offset
        ORDER BY s.start_time
    """
    with get_session() as s:
        return [dict(r) for r in s.execute(text(sql), {"tz": TZ_NAME, "offset": days_ahead}).mappings().all()]

def _sessions_next_hour() -> list[dict]:
    """
    Return sessions starting within the next hour.
    """
    sql = """
        WITH now_local AS (
            SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
        ),
        bounds AS (
            SELECT date_trunc('hour', ts) AS h,
                   date_trunc('hour', ts) + interval '1 hour' AS h_plus
            FROM now_local
        )
        SELECT s.id, s.session_date, s.start_time, s.capacity,
               s.booked_count, s.status,
               COALESCE((
                   SELECT STRING_AGG(c2.wa_number, ',')
                   FROM bookings b2
                   JOIN clients c2 ON c2.id = b2.client_id
                   WHERE b2.session_id = s.id
                     AND b2.status = 'confirmed'
               ), '') AS wa_numbers
        FROM sessions s, bounds
        WHERE (s.session_date + s.start_time) >= bounds.h
          AND (s.session_date + s.start_time) <  bounds.h_plus
        ORDER BY s.start_time
    """
    with get_session() as s:
        return [dict(r) for r in s.execute(text(sql), {"tz": TZ_NAME}).mappings().all()]

def _sessions_next_week() -> list[dict]:
    """
    Return sessions for the next 7 days.
    """
    sql = """
        WITH base AS (
            SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz)::date AS today
        )
        SELECT s.id, s.session_date, s.start_time,
               COALESCE((
                   SELECT STRING_AGG(c2.wa_number, ',')
                   FROM bookings b2
                   JOIN clients c2 ON c2.id = b2.client_id
                   WHERE b2.session_id = s.id
                     AND b2.status = 'confirmed'
               ), '') AS wa_numbers
        FROM sessions s, base
        WHERE s.session_date BETWEEN base.today AND base.today + 6
        ORDER BY s.session_date, s.start_time
    """
    with get_session() as s:
        return [dict(r) for r in s.execute(text(sql), {"tz": TZ_NAME}).mappings().all()]

# ─────────────────────────────────────────────
# Core senders
# ─────────────────────────────────────────────

def _send_client_template(to_wa: str, template: str, params: list[str]) -> None:
    send_whatsapp_template(
        normalize_wa(to_wa),
        template_name=template,
        lang="en",
        components=[{"type": "body", "parameters": [{"type": "text", "text": p} for p in params]}]
    )

def run_client_tomorrow() -> int:
    """
    Send 24h-before reminders using `session_tomorrow`.
    """
    sessions = _sessions_for_offset(1)
    sent = 0
    for sess in sessions:
        hhmm = str(sess["start_time"])[:5]
        for wa in (sess["wa_numbers"] or "").split(","):
            if not wa:
                continue
            _send_client_template(wa, "session_tomorrow", [hhmm])
            sent += 1
    logging.info(f"[CLIENT] tomorrow reminders sent={sent}")
    return sent

def run_client_next_hour() -> int:
    """
    Send 1h-before reminders using `session_next_hour`.
    """
    sessions = _sessions_next_hour()
    sent = 0
    for sess in sessions:
        hhmm = str(sess["start_time"])[:5]
        for wa in (sess["wa_numbers"] or "").split(","):
            if not wa:
                continue
            _send_client_template(wa, "session_next_hour", [hhmm])
            sent += 1
    logging.info(f"[CLIENT] next-hour reminders sent={sent}")
    return sent

def run_client_weekly() -> int:
    """
    Send weekly preview on Sundays 18:00 using `session_weekly`.
    Groups by client, compiles their week’s schedule.
    """
    sessions = _sessions_next_week()
    per_client: dict[str, list[str]] = {}

    for sess in sessions:
        day = sess["session_date"].strftime("%A")
        time = str(sess["start_time"])[:5]
        slot = f"{day} at {time}"
        for wa in (sess["wa_numbers"] or "").split(","):
            if not wa:
                continue
            per_client.setdefault(wa, []).append(slot)

    sent = 0
    for wa, slots in per_client.items():
        schedule = "\n".join(f"• {s}" for s in slots)
        msg = f"{schedule}\nLooking forward to seeing you!"
        _send_client_template(wa, "session_weekly", [msg])
        sent += 1

    logging.info(f"[CLIENT] weekly previews sent={sent}")
    return sent
