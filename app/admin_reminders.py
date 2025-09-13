# app/admin_reminders.py
from __future__ import annotations
import logging
from sqlalchemy import text
from .db import get_session
from .config import TZ_NAME, ADMIN_NUMBERS
from .templates import send_admin_hourly, send_admin_daily
from . import crud

# ─────────────────────────────────────────────
# SQL helpers
# ─────────────────────────────────────────────

def _rows_today(upcoming_only: bool) -> list[dict]:
    sql = f"""
        WITH now_local AS (
            SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
        )
        SELECT s.id, s.session_date, s.start_time, s.capacity,
               s.booked_count, s.status, COALESCE(s.notes,'') AS notes
        FROM sessions s, now_local
        WHERE s.session_date = (now_local.ts)::date
          {"AND s.start_time >= (now_local.ts)::time" if upcoming_only else ""}
        ORDER BY s.start_time
    """
    with get_session() as s:
        return [dict(r) for r in s.execute(text(sql), {"tz": TZ_NAME}).mappings().all()]

def _rows_next_hour() -> list[dict]:
    sql = """
        WITH now_local AS (
            SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
        )
        SELECT s.id, s.session_date, s.start_time, s.capacity,
               s.booked_count, s.status
        FROM sessions s, now_local
        WHERE s.session_date = (now_local.ts)::date
          AND s.start_time >= (date_trunc('hour', (now_local.ts)::time))
          AND s.start_time <  (date_trunc('hour', (now_local.ts)::time) + interval '1 hour')
        ORDER BY s.start_time
    """
    with get_session() as s:
        return [dict(r) for r in s.execute(text(sql), {"tz": TZ_NAME}).mappings().all()]

# ─────────────────────────────────────────────
# Core senders
# ─────────────────────────────────────────────

def run_admin_tick() -> None:
    """Send hourly admin summary via template."""
    today = _rows_today(upcoming_only=True)
    next_hour = _rows_next_hour()

    today_count = len(today)
    next_msg = "No upcoming sessions" if not next_hour else f"{next_hour[0]['start_time']}"

    for admin in ADMIN_NUMBERS:
        send_admin_hourly(admin, time=next_msg, count=today_count)

    crud.inbox_upsert(
        kind="hourly",
        title="Hourly update",
        body=f"next={next_msg} count={today_count}",
        source="cron",
        status="open",
        is_unread=True,
        action_required=False,
        digest=f"hourly-{next_msg}",
    )
    logging.info("[ADMIN] hourly update sent via template")

def run_admin_daily() -> None:
    """Send daily 20h00 recap via template."""
    today = _rows_today(upcoming_only=False)
    session_list = ", ".join([str(r["start_time"]) for r in today]) or "No sessions"

    for admin in ADMIN_NUMBERS:
        send_admin_daily(admin, count=len(today), sessions=session_list)

    crud.inbox_upsert(
        kind="recap",
        title="20h00 recap",
        body=session_list,
        source="cron",
        status="open",
        is_unread=True,
        action_required=False,
        digest=f"recap-{session_list[:20]}",
    )
    logging.info("[ADMIN] daily recap sent via template")
