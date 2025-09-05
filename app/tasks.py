# app/tasks.py
from __future__ import annotations

import logging
from flask import request
from sqlalchemy import text

from .db import get_session
from .utils import normalize_wa, send_whatsapp_text  # we only need plain text for admin pushes
from .config import NADINE_WA

# ─────────────────────────────────────────────────────────────────────────────
# SQL helpers (all time math is done in DB using Africa/Johannesburg)
# ─────────────────────────────────────────────────────────────────────────────

def _sessions_next_hour() -> list[dict]:
    """
    Sessions that start within the next hour (SA local).
    """
    with get_session() as s:
        rows = s.execute(text("""
            WITH now_local AS (
                SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE 'Africa/Johannesburg') AS ts
            ),
            win AS (
                SELECT ts, (ts + INTERVAL '1 hour') AS ts_plus FROM now_local
            )
            SELECT id, session_date, start_time, capacity, booked_count, status, COALESCE(notes,'') AS notes
            FROM sessions, win
            WHERE (session_date + start_time) >= win.ts
              AND (session_date + start_time) <  win.ts_plus
            ORDER BY start_time
        """)).mappings().all()
        return [dict(r) for r in rows]


def _sessions_today_upcoming() -> list[dict]:
    """
    Today’s sessions that are still upcoming (SA local).
    """
    with get_session() as s:
        rows = s.execute(text("""
            WITH now_local AS (
                SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE 'Africa/Johannesburg') AS ts
            )
            SELECT id, session_date, start_time, capacity, booked_count, status, COALESCE(notes,'') AS notes
            FROM sessions, now_local
            WHERE session_date = (now_local.ts)::date
              AND start_time   >= (now_local.ts)::time
            ORDER BY session_date, start_time
        """)).mappings().all()
        return [dict(r) for r in rows]


def _sessions_today_full_day() -> list[dict]:
    """
    All of today’s sessions (SA local).
    """
    with get_session() as s:
        rows = s.execute(text("""
            WITH now_local AS (
                SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE 'Africa/Johannesburg') AS ts
            )
            SELECT id, session_date, start_time, capacity, booked_count, status, COALESCE(notes,'') AS notes
            FROM sessions, now_local
            WHERE session_date = (now_local.ts)::date
            ORDER BY session_date, start_time
        """)).mappings().all()
        return [dict(r) for r in rows]


def _sessions_tomorrow_full_day() -> list[dict]:
    """
    All of tomorrow’s sessions (SA local).
    """
    with get_session() as s:
        rows = s.execute(text("""
            WITH now_local AS (
                SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE 'Africa/Johannesburg') AS ts
            )
            SELECT id, session_date, start_time, capacity, booked_count, status, COALESCE(notes,'') AS notes
            FROM sessions, now_local
            WHERE session_date = ((now_local.ts)::date + INTERVAL '1 day')::date
            ORDER BY session_date, start_time
        """)).mappings().all()
        return [dict(r) for r in rows]


def _attendee_names_for_session(session_id: int) -> list[str]:
    """
    Returns a list of attendee names (confirmed bookings) for the given session.
    Falls back to phone if name is null/blank.
    """
    with get_session() as s:
        rows = s.execute(text("""
            SELECT
              TRIM(COALESCE(NULLIF(c.name, ''), c.wa_number)) AS who
            FROM bookings b
            JOIN clients  c ON c.id = b.client_id
            WHERE b.session_id = :sid
              AND b.status = 'confirmed'
            ORDER BY who NULLS LAST
        """), {"sid": int(session_id)}).mappings().all()
        return [r["who"] or "" for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Formatting for ADMIN (shows client names)
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_rows_with_names(rows: list[dict]) -> str:
    """
    Each line: • HH:MM – status + attendee list
    Example:
      • 09:00 — ✅ open — Alice, Bob, Carol
    If there are no attendees yet, show “— (no bookings)”.
    """
    if not rows:
        return "— none —"
    out: list[str] = []
    for r in rows:
        hhmm = str(r["start_time"])[:5]
        full = (str(r["status"]).lower() == "full") or (r["booked_count"] >= r["capacity"])
        status = "🔒 full" if full else "✅ open"

        names = _attendee_names_for_session(r["id"])
        if names:
            names_str = ", ".join(names)
        else:
            names_str = "(no bookings)"

        out.append(f"• {hhmm} — {status} — {names_str}")
    return "\n".join(out)


def _fmt_today_block(include_upcoming_only: bool) -> str:
    """
    Header + formatted lines with names.
    """
    items = _sessions_today_upcoming() if include_upcoming_only else _sessions_today_full_day()
    header = (
        f"🗓 Today’s sessions (upcoming: {len(items)})"
        if include_upcoming_only else
        "🗓 Today’s sessions (full day)"
    )
    return f"{header}\n{_fmt_rows_with_names(items)}"


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

def register_tasks(app):
    @app.post("/tasks/admin-notify")
    def admin_notify():
        """
        Hourly admin summary to WhatsApp **with client names**:
          • At ~04:00 UTC (≈ 06:00 SA) → full-day.
          • Other hours → upcoming-only.
        Always append a “next hour” block with names.
        """
        try:
            src = request.args.get("src", "unknown")
            logging.info(f"[admin-notify] src={src}")

            # Use DB now() to pick the hour (UTC), then decide full-day vs upcoming.
            with get_session() as s:
                now_utc_hour = s.execute(text("SELECT EXTRACT(HOUR FROM now())::int AS h")).mappings().first()["h"]

            body_today = _fmt_today_block(include_upcoming_only=False if now_utc_hour == 4 else True)

            next_hour = _sessions_next_hour()
            nh_body = _fmt_rows_with_names(next_hour)
            nh_text = "🕒 Next hour:\n" + nh_body

            msg = f"{body_today}\n\n{nh_text}"

            to = normalize_wa(NADINE_WA)
            if not to:
                logging.warning("[admin-notify] NADINE_WA not configured.")
                return "ok", 200

            send_whatsapp_text(to, msg)  # ignoring return tuple on purpose
            logging.info("[TASKS] admin-notify sent")
            return "ok", 200

        except Exception:
            logging.exception("admin-notify failed")
            return "error", 500

    @app.post("/tasks/run-reminders")
    def run_reminders():
        """
        - daily=0 (default): send client next-hour reminders (to clients).
        - daily=1: admin recap for today (fallback/manual) — with names.
        """
        try:
            src = request.args.get("src", "unknown")
            daily = request.args.get("daily", "0") == "1"
            logging.info(f"[run-reminders] src={src}")

            if daily:
                # Admin daily recap — include names
                today_all = _sessions_today_full_day()
                header = "🗓 Today’s sessions (full day)"
                body   = _fmt_rows_with_names(today_all)

                to = normalize_wa(NADINE_WA)
                if to:
                    send_whatsapp_text(to, f"{header}\n{body}")
                logging.info(f"[TASKS] run-reminders sent=0 [run-reminders] src={src}")
                return "ok sent=0", 200

            # Hourly client reminders (to attendees) — unchanged logic
            rows = _sessions_next_hour()
            sent = 0
            if not rows:
                logging.info(f"[TASKS] run-reminders sent={sent} [run-reminders] src={src}")
                return f"ok sent={sent}", 200

            with get_session() as s:
                for sess in rows:
                    attendees = s.execute(text("""
                        SELECT c.wa_number AS wa
                        FROM bookings b
                        JOIN clients  c ON c.id = b.client_id
                        WHERE b.session_id = :sid AND b.status = 'confirmed'
                    """), {"sid": sess["id"]}).mappings().all()

                    if not attendees:
                        continue

                    hhmm = str(sess["start_time"])[:5]
                    for a in attendees:
                        send_whatsapp_text(
                            normalize_wa(a["wa"]),
                            f"⏰ Reminder: Your Pilates session starts at {hhmm} today. Reply CANCEL if you cannot attend."
                        )
                        sent += 1

            logging.info(f"[TASKS] run-reminders sent={sent} [run-reminders] src={src}")
            return f"ok sent={sent}", 200

        except Exception:
            logging.exception("run-reminders failed")
            return "error", 500

    @app.post("/tasks/debug-ping-admin")
    def debug_ping_admin():
        try:
            to = normalize_wa(NADINE_WA)
            logging.info(f"[debug] NADINE_WA={repr(NADINE_WA)} (normalized='{to}')")
            if not to:
                return "missing admin", 400
            send_whatsapp_text(to, "Ping from /tasks/debug-ping-admin ✅")
            return "sent", 200
        except Exception:
            logging.exception("debug-ping-admin failed")
            return "error", 500
