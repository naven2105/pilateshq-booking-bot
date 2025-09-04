# app/tasks.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from flask import request
from sqlalchemy import text

from .db import get_session
from .utils import normalize_wa, send_whatsapp_text, send_whatsapp_template
from .config import NADINE_WA, TZ_NAME  # ← now we import TZ_NAME here

# ───────────────────────────
# Session lookups (local TZ)
# ───────────────────────────

def _sessions_next_hour():
    """Sessions that start within the next hour (local TZ from TZ_NAME)."""
    with get_session() as s:
        rows = s.execute(text("""
            WITH now_local AS (
                SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
            ),
            window AS (
                SELECT ts, (ts + INTERVAL '1 hour') AS ts_plus FROM now_local
            )
            SELECT id, session_date, start_time, capacity, booked_count, status, COALESCE(notes,'') AS notes
            FROM sessions, window
            WHERE (session_date + start_time) >= window.ts
              AND (session_date + start_time) <  window.ts_plus
            ORDER BY start_time
        """), {"tz": TZ_NAME}).mappings().all()
        return [dict(r) for r in rows]

def _sessions_today_upcoming():
    """Today’s sessions that are still upcoming (local TZ)."""
    with get_session() as s:
        rows = s.execute(text("""
            WITH now_local AS (
                SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
            )
            SELECT id, session_date, start_time, capacity, booked_count, status, COALESCE(notes,'') AS notes
            FROM sessions, now_local
            WHERE session_date = (now_local.ts)::date
              AND start_time >= (now_local.ts)::time
            ORDER BY session_date, start_time
        """), {"tz": TZ_NAME}).mappings().all()
        return [dict(r) for r in rows]

def _sessions_today_full_day():
    """All of today’s sessions (local TZ date)."""
    with get_session() as s:
        rows = s.execute(text("""
            WITH now_local AS (
                SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
            )
            SELECT id, session_date, start_time, capacity, booked_count, status, COALESCE(notes,'') AS notes
            FROM sessions, now_local
            WHERE session_date = (now_local.ts)::date
            ORDER BY session_date, start_time
        """), {"tz": TZ_NAME}).mappings().all()
        return [dict(r) for r in rows]

def _sessions_tomorrow_full_day():
    """All of tomorrow’s sessions (local TZ date)."""
    with get_session() as s:
        rows = s.execute(text("""
            WITH now_local AS (
                SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
            )
            SELECT id, session_date, start_time, capacity, booked_count, status, COALESCE(notes,'') AS notes
            FROM sessions, now_local
            WHERE session_date = ((now_local.ts)::date + INTERVAL '1 day')::date
            ORDER BY session_date, start_time
        """), {"tz": TZ_NAME}).mappings().all()
        return [dict(r) for r in rows]
    