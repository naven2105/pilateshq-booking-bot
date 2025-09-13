# app/admin_reminders.py
from __future__ import annotations
import logging
from sqlalchemy import text
from .db import get_session
from .utils import normalize_wa, send_whatsapp_template
from .config import TZ_NAME, ADMIN_NUMBERS
from . import crud

# ─────────────────────────────────────────────
# SQL helpers
# ─────────────────────────────────────────────

def _rows_today(upcoming_only: bool) -> list[dict]:
    sql = f"""
        WITH now_local AS (
            SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
        ),
        pool AS (
            SELECT s.id, s.session_date, s.start_time, s.capacity,
                   s.booked_count, s.status, COALESCE(s.notes,'') AS notes
            FROM sessions s, now_local
            WHERE s.session_date = (now_local.ts)::date
            {"AND s.start_time >= (now_local.ts)::time" if upcoming_only else ""}
        )
        SELECT
            p.*,
            COALESCE((
                SELECT STRING_AGG(nm, ', ' ORDER BY nm)
                FROM (
                    SELECT DISTINCT COALESCE(c2.name, '') AS nm
                    FROM bookings b2
                    JOIN clients  c2 ON c2.id = b2.client_id
                    WHERE b2.session_id = p.id
                      AND b2.status = 'confirmed'
                ) d
            ), '') AS names
        FROM pool p
        ORDER BY p.session_date, p.start_time
    """
    with get_session() as s:
        return [dict(r) for r in s.execute(text(sql), {"tz": TZ_NAME}).mappings().all()]

def _rows_upcoming_hours() -> str:
    sql = """
        WITH now_local AS (
            SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
        ),
        bounds AS (
            SELECT generate_series(
                date_trunc('hour', ts) + interval '1 hour',
                date_trunc('day', ts) + interval '18 hour',
                interval '1 hour'
            ) AS h
            FROM now_local
        )
        SELECT
            b.h AS block_start,
            b.h + interval '1 hour' AS block_end,
            s.id, s.session_date, s.start_time, s.capacity,
            s.booked_count, s.status,
            COALESCE((
                SELECT STRING_AGG(nm, ', ' ORDER BY nm)
                FROM (
                    SELECT DISTINCT COALESCE(c2.name, '') AS nm
                    FROM bookings b2
                    JOIN clients  c2 ON c2.id = b2.client_id
                    WHERE b2.session_id = s.id
                      AND b2.status = 'confirmed'
                ) d
            ), '') AS names
        FROM bounds b
        LEFT JOIN sessions s
          ON (s.session_date + s.start_time) >= b.h
         AND (s.session_date + s.start_time) <  b.h + interval '1 hour'
         AND s.session_date = (b.h)::date
        ORDER BY b.h, s.start_time
    """
    with get_session() as s:
        rows = [dict(r) for r in s.execute(text(sql), {"tz": TZ_NAME}).mappings().all()]

    out = []
    for r in rows:
        if r["id"] is None:
            continue
        hhmm = str(r["start_time"])[:5]
        booked = str(r["names"] or "0")
        out.append((hhmm, booked))
    return out

# ─────────────────────────────────────────────
# Core senders
# ─────────────────────────────────────────────

def run_admin_tick() -> None:
    """
    Hourly admin summary via template.
    """
    hours = _rows_upcoming_hours()
    today = _rows_today(upcoming_only=True)

    total = len(today)
    detail = ", ".join([f"{h} ({b})" for h, b in hours]) or "No sessions upcoming"

    for admin in ADMIN_NUMBERS:
        send_whatsapp_template(normalize_wa(admin), "admin_hourly_update", [detail, str(total)])

    crud.inbox_upsert(
        kind="hourly",
        title="Hourly update",
        body=detail,
        source="cron",
        status="open",
        is_unread=True,
        action_required=False,
        digest=f"hourly-{detail[:20]}",
    )
    logging.info("[ADMIN_REMINDERS] hourly update sent + inbox")

def run_daily_recap() -> None:
    """
    20:00 recap for admins via template.
    """
    today = _rows_today(upcoming_only=False)
    detail = "\n".join([f"{str(r['start_time'])[:5]} — {r.get('names') or 'no bookings'}" for r in today]) or "— none —"

    for admin in ADMIN_NUMBERS:
        send_whatsapp_template(normalize_wa(admin), "admin_20h00", [str(len(today)), detail])

    crud.inbox_upsert(
        kind="recap",
        title="20:00 recap",
        body=detail,
        source="cron",
        status="open",
        is_unread=True,
        action_required=False,
        digest=f"recap-{detail[:20]}",
    )
    logging.info("[ADMIN_REMINDERS] recap sent + inbox")
