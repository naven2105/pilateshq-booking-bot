# app/tasks.py
from __future__ import annotations

import logging
from datetime import datetime
from flask import request
from sqlalchemy import text

from .db import get_session
from .utils import normalize_wa, send_whatsapp_text
from .config import NADINE_WA, TZ_NAME


# ───────────────────────────
# SQL helpers (Africa/Johannesburg local)
# ───────────────────────────

def _rows_today_upcoming(include_names: bool = True) -> list[dict]:
    """
    All of *today's* sessions that are still upcoming (>= now local).
    """
    with get_session() as s:
        sql = text(f"""
            WITH now_local AS (
                SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
            ),
            upcoming AS (
                SELECT s.id, s.session_date, s.start_time,
                       s.capacity, s.booked_count, s.status, COALESCE(s.notes,'') AS notes
                FROM sessions s, now_local
                WHERE s.session_date = (now_local.ts)::date
                  AND s.start_time  >= (now_local.ts)::time
            )
            SELECT
                u.*,
                COALESCE((
                    SELECT STRING_AGG(nm, ', ' ORDER BY nm)
                    FROM (
                        SELECT DISTINCT COALESCE(c2.name, '') AS nm
                        FROM bookings b2
                        JOIN clients  c2 ON c2.id = b2.client_id
                        WHERE b2.session_id = u.id
                          AND b2.status = 'confirmed'
                    ) d
                ), '') AS names
            FROM upcoming u
            ORDER BY u.session_date, u.start_time
        """)
        rows = [dict(r) for r in s.execute(sql, {"tz": TZ_NAME}).mappings().all()]
        if not include_names:
            for r in rows:
                r["names"] = ""
        return rows


def _rows_today_full_day(include_names: bool = True) -> list[dict]:
    """
    All of *today's* sessions (full day in local time).
    """
    with get_session() as s:
        sql = text(f"""
            WITH now_local AS (
                SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
            )
            SELECT
                s.id, s.session_date, s.start_time,
                s.capacity, s.booked_count, s.status, COALESCE(s.notes,'') AS notes,
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
            FROM sessions s, now_local
            WHERE s.session_date = (now_local.ts)::date
            ORDER BY s.session_date, s.start_time
        """)
        rows = [dict(r) for r in s.execute(sql, {"tz": TZ_NAME}).mappings().all()]
        if not include_names:
            for r in rows:
                r["names"] = ""
        return rows


def _row_next_upcoming(include_names: bool = True) -> dict | None:
    """
    The next session >= now (local), today or later.
    """
    with get_session() as s:
        sql = text(f"""
            WITH now_local AS (
                SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
            )
            SELECT
                s.id, s.session_date, s.start_time,
                s.capacity, s.booked_count, s.status, COALESCE(s.notes,'') AS notes,
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
            FROM sessions s, now_local
            WHERE (s.session_date + s.start_time) >= now_local.ts
            ORDER BY s.session_date, s.start_time
            LIMIT 1
        """)
        row = s.execute(sql, {"tz": TZ_NAME}).mappings().first()
        if not row:
            return None
        d = dict(row)
        if not include_names:
            d["names"] = ""
        return d


def _rows_tomorrow_full_day(include_names: bool = True) -> list[dict]:
    """
    All of *tomorrow's* sessions (local date).
    """
    with get_session() as s:
        sql = text(f"""
            WITH now_local AS (
                SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
            )
            SELECT
                s.id, s.session_date, s.start_time,
                s.capacity, s.booked_count, s.status, COALESCE(s.notes,'') AS notes,
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
            FROM sessions s, now_local
            WHERE s.session_date = ((now_local.ts)::date + INTERVAL '1 day')::date
            ORDER BY s.session_date, s.start_time
        """)
        rows = [dict(r) for r in s.execute(sql, {"tz": TZ_NAME}).mappings().all()]
        if not include_names:
            for r in rows:
                r["names"] = ""
        return rows


# ───────────────────────────
# Formatting
# ───────────────────────────

def _status_emoji(r: dict) -> str:
    full = (str(r.get("status", "")).lower() == "full") or (r.get("booked_count", 0) >= r.get("capacity", 0))
    return "🔒 full" if full else "✅ open"

def _fmt_names(r: dict) -> str:
    names = (r.get("names") or "").strip()
    return names if names else "(no bookings)"

def _fmt_rows(rows: list[dict]) -> str:
    if not rows:
        return "— none —"
    out = []
    for r in rows:
        hhmm = str(r["start_time"])[:5]
        out.append(f"• {hhmm} – {_fmt_names(r)}  ({_status_emoji(r)})")
    return "\n".join(out)

def _fmt_today_block(upcoming_only: bool, include_names: bool = True) -> str:
    rows = _rows_today_upcoming(include_names=include_names) if upcoming_only else _rows_today_full_day(include_names=include_names)
    if upcoming_only:
        header = f"🗓 Today’s sessions (upcoming: {len(rows)})"
    else:
        header = f"🗓 Today’s sessions (full day: {len(rows)})"
    return f"{header}\n{_fmt_rows(rows)}"

def _fmt_one_line(r: dict, prefix: str) -> str:
    if not r:
        return f"{prefix}: none."
    hhmm = str(r["start_time"])[:5]
    # If the next upcoming is not today, include the date
    return f"{prefix}: {r['session_date']} {hhmm} – {_fmt_names(r)}  ({_status_emoji(r)})"


# ───────────────────────────
# Routes
# ───────────────────────────

def register_tasks(app):
    @app.post("/tasks/admin-notify")
    def admin_notify():
        """
        Hourly admin summary + next upcoming.
        - At ~04:00 UTC (≈ 06:00 SAST) show full-day; other hours: upcoming-only.
        - Always show “Next upcoming” (today or later).
        - If daily=1: send a 20:00-style recap of *tomorrow* (with names).
        """
        try:
            src = request.args.get("src", "unknown")
            daily = request.args.get("daily", "0") == "1"
            logging.info(f"[admin-notify] src={src} daily={daily}")

            to = normalize_wa(NADINE_WA)
            if not to:
                logging.warning("[admin-notify] NADINE_WA not configured; skipping send.")
                return "ok", 200

            if daily:
                # 20:00 recap → tomorrow (with names)
                rows = _rows_tomorrow_full_day(include_names=True)
                header = f"🗓 Tomorrow’s sessions ({len(rows)})"
                msg = f"{header}\n{_fmt_rows(rows)}"
                send_whatsapp_text(to, msg)
                logging.info("[TASKS] admin-notify (daily) sent")
                return "ok", 200

            # Determine UTC hour via DB to avoid container TZ surprises
            with get_session() as s:
                now_utc_hour = s.execute(text("SELECT EXTRACT(HOUR FROM now())::int AS h")).mappings().first()["h"]

            body_today = _fmt_today_block(
                upcoming_only=False if now_utc_hour == 4 else True,
                include_names=True,
            )

            nxt = _row_next_upcoming(include_names=True)
            nxt_line = _fmt_one_line(nxt, "🕒 Next upcoming")

            msg = f"{body_today}\n\n{nxt_line}"

            send_whatsapp_text(to, msg)
            logging.info("[TASKS] admin-notify sent")
            return "ok", 200

        except Exception:
            logging.exception("admin-notify failed")
            return "error", 500

    @app.post("/tasks/run-reminders")
    def run_reminders():
        """
        Client reminders for the next upcoming *hourly* window were used before,
        but we now keep this endpoint for compatibility and possible client pings.
        For now it only logs; admin notifications are handled by /tasks/admin-notify.
        """
        try:
            src = request.args.get("src", "unknown")
            logging.info(f"[run-reminders] src={src}")
            # No-op (or keep your previous client reminder code if you still use it)
            logging.info("[TASKS] run-reminders noop")
            return "ok", 200
        except Exception:
            logging.exception("run-reminders failed")
            return "error", 500
