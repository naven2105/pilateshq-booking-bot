# app/admin_reminders.py
from __future__ import annotations
import logging
from sqlalchemy import text
from .db import get_session
from .utils import normalize_wa
from .config import TZ_NAME, ADMIN_NUMBERS
from . import crud
from .templates import send_admin_hourly, send_admin_daily


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


# ─────────────────────────────────────────────
# Admin reminder logic
# ─────────────────────────────────────────────

def run_admin_tick() -> None:
    """
    Hourly admin summary: today’s upcoming + next-hour template push.
    """
    today = _rows_today(upcoming_only=True)
    today_count = len(today)
    next_msg = today[0]["start_time"].strftime("%H:%M") if today else "—"

    for admin in ADMIN_NUMBERS:
        # ✅ Fixed: match template param names
        send_admin_hourly(admin, session_time=next_msg, booking_status=today_count)

    crud.inbox_upsert(
        kind="hourly",
        title="Hourly update",
        body=f"Sessions today={today_count}, next={next_msg}",
        source="cron",
        status="open",
        is_unread=True,
        action_required=False,
        digest=f"hourly-{today_count}-{next_msg}",
    )
    logging.info("[ADMIN] hourly tick sent")


def run_admin_daily() -> None:
    """
    Daily admin recap at 20:00 using template.
    """
    today = _rows_today(upcoming_only=False)
    today_count = len(today)
    today_list = "\n".join(
        f"• {str(r['start_time'])[:5]} — {(r.get('names') or 'no bookings')}"
        for r in today
    ) or "— none —"

    for admin in ADMIN_NUMBERS:
        send_admin_daily(admin, count=today_count, details=today_list)

    crud.inbox_upsert(
        kind="recap",
        title="20:00 recap",
        body=f"Sessions today={today_count}",
        source="cron",
        status="open",
        is_unread=True,
        action_required=False,
        digest=f"recap-{today_count}",
    )
    logging.info("[ADMIN] daily recap sent")
