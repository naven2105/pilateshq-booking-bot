# app/client_reminders.py
from __future__ import annotations
import logging
from sqlalchemy import text
from .db import get_session
from .templates import send_client_tomorrow, send_client_next_hour, send_client_weekly

# ─────────────────────────────────────────────
# SQL helpers
# ─────────────────────────────────────────────

def _sessions_tomorrow() -> list[dict]:
    sql = """
        SELECT b.id, c.wa_number, c.name, s.session_date, s.start_time
        FROM bookings b
        JOIN clients c ON c.id = b.client_id
        JOIN sessions s ON s.id = b.session_id
        WHERE b.status = 'confirmed'
          AND s.session_date = (CURRENT_DATE + interval '1 day')
        ORDER BY s.start_time
    """
    with get_session() as s:
        return [dict(r) for r in s.execute(text(sql)).mappings().all()]

def _sessions_next_hour() -> list[dict]:
    sql = """
        WITH now_local AS (
            SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE 'Africa/Johannesburg') AS ts
        )
        SELECT b.id, c.wa_number, c.name, s.session_date, s.start_time
        FROM bookings b
        JOIN clients c ON c.id = b.client_id
        JOIN sessions s ON s.id = b.session_id, now_local
        WHERE b.status = 'confirmed'
          AND s.session_date = (now_local.ts)::date
          AND s.start_time >= (date_trunc('hour', (now_local.ts)::time))
          AND s.start_time <  (date_trunc('hour', (now_local.ts)::time) + interval '1 hour')
        ORDER BY s.start_time
    """
    with get_session() as s:
        return [dict(r) for r in s.execute(text(sql)).mappings().all()]

def _sessions_week_ahead() -> list[dict]:
    sql = """
        SELECT b.id, c.wa_number, c.name, s.session_date, s.start_time
        FROM bookings b
        JOIN clients c ON c.id = b.client_id
        JOIN sessions s ON s.id = b.session_id
        WHERE b.status = 'confirmed'
          AND s.session_date BETWEEN CURRENT_DATE AND CURRENT_DATE + interval '7 days'
        ORDER BY s.session_date, s.start_time
    """
    with get_session() as s:
        return [dict(r) for r in s.execute(text(sql)).mappings().all()]

# ─────────────────────────────────────────────
# Core senders
# ─────────────────────────────────────────────

def run_client_tomorrow() -> int:
    rows = _sessions_tomorrow()
    sent = 0
    for r in rows:
        send_client_tomorrow(r["wa_number"], str(r["start_time"]))
        sent += 1
    logging.info("[CLIENT] tomorrow reminders sent=%s", sent)
    return sent

def run_client_next_hour() -> int:
    rows = _sessions_next_hour()
    sent = 0
    for r in rows:
        send_client_next_hour(r["wa_number"], str(r["start_time"]))
        sent += 1
    logging.info("[CLIENT] next-hour reminders sent=%s", sent)
    return sent

def run_client_weekly() -> int:
    rows = _sessions_week_ahead()
    sent = 0
    for r in rows:
        msg = f"{r['session_date']} at {r['start_time']}"
        send_client_weekly(r["wa_number"], msg)
        sent += 1
    logging.info("[CLIENT] weekly reminders sent=%s", sent)
    return sent
