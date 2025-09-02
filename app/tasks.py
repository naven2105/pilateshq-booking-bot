# app/tasks.py
from __future__ import annotations

import logging
from flask import request
from sqlalchemy import text

from .db import get_session
from .utils import send_whatsapp_text, normalize_wa
from .config import NADINE_WA

# ──────────────────────────────────────────────────────────────────────────────
# SQL helpers (Africa/Johannesburg local-time aware using Postgres)
# sessions table: id, session_date::date, start_time::time, capacity, booked_count, status
# ──────────────────────────────────────────────────────────────────────────────

def _sessions_today_full_day():
    """
    All of today's sessions (local SAST), ordered by time.
    """
    with get_session() as s:
        rows = s.execute(text("""
            WITH tz AS (
              SELECT (now() AT TIME ZONE 'Africa/Johannesburg')::date AS today
            )
            SELECT id, session_date, start_time, capacity, booked_count, status
            FROM sessions, tz
            WHERE session_date = tz.today
            ORDER BY start_time
        """)).mappings().all()
        return [dict(r) for r in rows]

def _sessions_today_upcoming():
    """
    Today's sessions from 'now' onwards (local SAST), ordered by time.
    """
    with get_session() as s:
        rows = s.execute(text("""
            WITH now_local AS (
              SELECT (now() AT TIME ZONE 'Africa/Johannesburg') AS ts
            )
            SELECT id, session_date, start_time, capacity, booked_count, status
            FROM sessions, now_local
            WHERE session_date = (now_local.ts)::date
              AND start_time >= (now_local.ts)::time
            ORDER BY start_time
        """)).mappings().all()
        return [dict(r) for r in rows]

def _sessions_next_hour():
    """
    Sessions starting within the next hour (local SAST).
    """
    with get_session() as s:
        rows = s.execute(text("""
            WITH now_local AS (
              SELECT (now() AT TIME ZONE 'Africa/Johannesburg') AS ts
            )
            SELECT id, session_date, start_time, capacity, booked_count, status
            FROM sessions, now_local
            WHERE session_date = (now_local.ts)::date
              AND start_time >= (now_local.ts)::time
              AND start_time < ((now_local.ts + interval '1 hour')::time)
            ORDER BY start_time
        """)).mappings().all()
        return [dict(r) for r in rows]

def _sessions_tomorrow_full_day():
    """
    All of tomorrow's sessions (local SAST), ordered by time.
    Useful for 20:00 'tomorrow preview'.
    """
    with get_session() as s:
        rows = s.execute(text("""
            WITH tz AS (
              SELECT ((now() AT TIME ZONE 'Africa/Johannesburg')::date + INTERVAL '1 day')::date AS d
            )
            SELECT id, session_date, start_time, capacity, booked_count, status
            FROM sessions, tz
            WHERE session_date = tz.d
            ORDER BY start_time
        """)).mappings().all()
        return [dict(r) for r in rows]

# ──────────────────────────────────────────────────────────────────────────────
# Formatting helpers
# ──────────────────────────────────────────────────────────────────────────────

def _fmt_status_emoji(status: str) -> str:
    st = (status or "").lower()
    if st == "full":
        return "🔒"
    if st == "open":
        return "✅"
    return "•"

def _fmt_line(r: dict) -> str:
    hhmm = str(r["start_time"])  # e.g., '09:00:00'
    # show HH:MM only
    hhmm = hhmm[:5]
    cap = int(r.get("capacity") or 0)
    bkd = int(r.get("booked_count") or 0)
    st  = str(r.get("status") or "")
    return f"• {hhmm} ({bkd}/{cap}, {st} {_fmt_status_emoji(st)})"

def _fmt_block(title: str, items: list[dict]) -> str:
    if not items:
        return f"{title}\n—\u00A0none\u00A0—"  # keep styling with NBSPs
    lines = [title] + [_fmt_line(r) for r in items]
    return "\n".join(lines)

def _fmt_today_block(upcoming_only: bool) -> str:
    """
    Title shows count of upcoming sessions so Nadine sees at a glance.
    """
    items = _sessions_today_upcoming() if upcoming_only else _sessions_today_full_day()
    header = f"🗓 Today’s sessions (upcoming: {len(items)})" if upcoming_only else "🗓 Today’s sessions"
    return _fmt_block(header, items)

def _fmt_next_hour_block() -> str:
    items = _sessions_next_hour()
    header = "🕒 Next hour:"
    return _fmt_block(header, items)

def _fmt_tomorrow_block() -> str:
    items = _sessions_tomorrow_full_day()
    header = "🔮 Tomorrow’s sessions:"
    return _fmt_block(header, items)

# ──────────────────────────────────────────────────────────────────────────────
# Flask route registration
# ──────────────────────────────────────────────────────────────────────────────

def register_tasks(app):
    """
    Exposes:
      POST /tasks/admin-notify         → sends “today (upcoming only)” + “next hour”
      POST /tasks/run-reminders?daily=0|1
           daily=0 → sends “next hour” (hourly cron)
           daily=1 → sends “today full-day + tomorrow preview” (20:00 cron)
      POST /tasks/debug-ping-admin     → quick delivery check
    """
    @app.post("/tasks/admin-notify")
    def admin_notify():
        try:
            src = request.args.get("src", "manual")
            logging.info(f"[admin-notify] src={src}")

            to = normalize_wa(NADINE_WA)
            if not to:
                logging.error("[admin-notify] NADINE_WA is empty")
                return "err", 500

            body_today = _fmt_today_block(upcoming_only=True)
            body_hour = _fmt_next_hour_block()
            msg = f"{body_today}\n\n{body_hour}"

            code, resp = send_whatsapp_text(to, msg)
            if code == 400 and "470" in resp:
                logging.warning("[admin-notify] Outside 24h window; ask Nadine to send 'Admin' to reopen the session.")
            logging.info("[TASKS] admin-notify sent")
            return "ok", 200
        except Exception as e:
            logging.exception(e)
            return "err", 500

    @app.post("/tasks/run-reminders")
    def run_reminders():
        """
        Hourly:   daily=0 → “next hour” only
        Nightly:  daily=1 → “today (full) + tomorrow”
        """
        try:
            src = request.args.get("src", "manual")
            daily_flag = (request.args.get("daily", "0") == "1")
            logging.info(f"[run-reminders] src={src}")

            to = normalize_wa(NADINE_WA)
            if not to:
                return "ok sent=0", 200

            if daily_flag:
                # 20:00 recap (full day) + tomorrow preview
                msg = f"{_fmt_today_block(upcoming_only=False)}\n\n{_fmt_tomorrow_block()}"
            else:
                # hourly window (just the next hour)
                msg = _fmt_next_hour_block()

            code, resp = send_whatsapp_text(to, msg)
            if code == 400 and "470" in resp:
                logging.warning("[run-reminders] Outside 24h window; ask Nadine to send 'Admin' to reopen the session.")

            logging.info(f"[TASKS] run-reminders sent=1 [run-reminders] src={src}")
            return "ok sent=1", 200
        except Exception as e:
            logging.exception(e)
            return "err", 500

    @app.post("/tasks/debug-ping-admin")
    def debug_ping_admin():
        """
        Quick “hello” to confirm delivery without running SQL.
        """
        to = normalize_wa(NADINE_WA)
        if not to:
            logging.error("[debug] NADINE_WA empty")
            return "err", 500
        logging.info(f"[debug] NADINE_WA='{NADINE_WA}' (normalized='{to}')")
        send_whatsapp_text(to, "👋 Debug ping from server.")
        return "sent", 200
