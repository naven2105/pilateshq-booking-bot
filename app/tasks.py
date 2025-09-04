# app/tasks.py
from __future__ import annotations

import logging
from flask import request
from sqlalchemy import text

from .db import get_session
from .utils import (
    normalize_wa,
    send_whatsapp_text,
    send_whatsapp_template,
)
from .config import NADINE_WA


# ──────────────────────────────────────────────────────────────────────────────
# Helpers: time-windowed session queries (Africa/Johannesburg local time)
# ──────────────────────────────────────────────────────────────────────────────

def _sessions_next_hour():
    """
    Return sessions that start within the next hour (local SA time).
    """
    with get_session() as s:
        rows = s.execute(text("""
            WITH now_local AS (
                SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE 'Africa/Johannesburg') AS ts
            ),
            window AS (
                SELECT ts, (ts + INTERVAL '1 hour') AS ts_plus
                FROM now_local
            )
            SELECT id, session_date, start_time, capacity, booked_count, status, COALESCE(notes,'') AS notes
            FROM sessions, window
            WHERE (session_date + start_time) >= window.ts
              AND (session_date + start_time) <  window.ts_plus
            ORDER BY start_time
        """)).mappings().all()
        return [dict(r) for r in rows]


def _sessions_today_upcoming():
    """
    Return TODAY’s sessions that are still upcoming (start_time >= now SA).
    """
    with get_session() as s:
        rows = s.execute(text("""
            WITH now_local AS (
                SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE 'Africa/Johannesburg') AS ts
            )
            SELECT id, session_date, start_time, capacity, booked_count, status, COALESCE(notes,'') AS notes
            FROM sessions, now_local
            WHERE session_date = (now_local.ts)::date
              AND start_time >= (now_local.ts)::time
            ORDER BY session_date, start_time
        """)).mappings().all()
        return [dict(r) for r in rows]


def _sessions_today_full_day():
    """
    Return all of TODAY’s sessions (SA local date), regardless of past/upcoming.
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


def _sessions_tomorrow_full_day():
    """
    Return all of TOMORROW’s sessions (SA local tomorrow).
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


# ──────────────────────────────────────────────────────────────────────────────
# Formatting
# ──────────────────────────────────────────────────────────────────────────────

def _fmt_rows(rows):
    """
    Format a list of sessions into bullet lines like:
    • 09:00 (3/6, ✅ open)   OR   • 08:00 (6/6, 🔒 full)
    """
    if not rows:
        return "— none —"
    out = []
    for r in rows:
        seats = f"{r['booked_count']}/{r['capacity']}"
        status = "🔒 full" if str(r["status"]).lower() == "full" or (r["booked_count"] >= r["capacity"]) else "✅ open"
        out.append(f"• {str(r['start_time'])[:5]} ({seats}, {status})")
    return "\n".join(out)


def _fmt_today_block(upcoming_only: bool):
    """
    Block text for today's sessions.
    At 06:00 SA and later, we typically show upcoming_only=True in hourly pings.
    For the 04:00 SA “morning digest” we can show the full day.
    """
    items = _sessions_today_upcoming() if upcoming_only else _sessions_today_full_day()
    header = f"🗓 Today’s sessions (upcoming: {len(items)})" if upcoming_only else "🗓 Today’s sessions (full day)"
    return f"{header}\n{_fmt_rows(items)}"


# ──────────────────────────────────────────────────────────────────────────────
# Route handlers
# ──────────────────────────────────────────────────────────────────────────────

def register_tasks(app):
    """
    Registers three task endpoints:

      POST /tasks/admin-notify
        - Sends admin a daily/hourly schedule summary.
        - Decides "upcoming-only" vs "full day" automatically by time.

      POST /tasks/run-reminders?daily=0|1
        - daily=0 (default): client “next-hour” reminders (if any).
        - daily=1: admin 20:00 daily recap (uses today's SA date).

      POST /tasks/debug-ping-admin
        - Sends a simple text message to admin (connectivity test).
    """

    @app.post("/tasks/admin-notify")
    def admin_notify():
        """
        Hourly admin notifications (called from Render cron).
        Behavior:
          - Around 04:00 SA → show full-day view for today.
          - Otherwise       → upcoming-only view for today.
          - Also attach a “next hour” line (even if none).
        """
        try:
            src = request.args.get("src", "unknown")
            logging.info(f"[admin-notify] src={src}")

            # we just need UTC hour as a rough guard; the SQL itself is localised
            # use DB to decide full/upcoming based on local hour if you prefer
            # here: treat “first daily pass” as full-day at 04:00 SA
            with get_session() as s:
                now_utc_hour = s.execute(text("SELECT EXTRACT(HOUR FROM now())::int AS h")).mappings().first()["h"]

            body_today = _fmt_today_block(upcoming_only=False if now_utc_hour == 4 else True)

            next_hour = _sessions_next_hour()
            if next_hour:
                nh_text = "🕒 Next hour:\n" + _fmt_rows(next_hour)
            else:
                nh_text = "🕒 Next hour: no upcoming session."

            msg = f"{body_today}\n\n{nh_text}"

            to = normalize_wa(NADINE_WA)
            if not to:
                logging.warning("[admin-notify] NADINE_WA not configured.")
                return "ok", 200

            # Send plain text (you can swap to a template if you prefer)
            send_whatsapp_text(to, msg)
            logging.info("[TASKS] admin-notify sent")
            return "ok", 200

        except Exception as e:
            logging.exception(e)
            return "error", 500

    @app.post("/tasks/run-reminders")
    def run_reminders():
        """
        Two modes:
         - daily=0 (default): send client “next-hour” reminders.
         - daily=1          : send admin 20:00 daily recap (optional keep).
        """
        try:
            src = request.args.get("src", "unknown")
            daily = request.args.get("daily", "0") == "1"
            logging.info(f"[run-reminders] src={src}")

            if daily:
                # 20:00 SA daily recap to ADMIN (today’s summary)
                today_all = _sessions_today_full_day()
                header = f"🗓 Today’s sessions (upcoming: {len([r for r in today_all if r['status'] != 'cancelled'])})"
                body = _fmt_rows(today_all)
                msg = f"{header}\n{body}"

                to = normalize_wa(NADINE_WA)
                if to:
                    send_whatsapp_text(to, msg)
                logging.info(f"[TASKS] run-reminders sent=0 [run-reminders] src={src}")
                return "ok sent=0", 200

            # Hourly: client “next hour” reminders
            rows = _sessions_next_hour()
            sent = 0
            if not rows:
                logging.info(f"[TASKS] run-reminders sent={sent} [run-reminders] src={src}")
                return f"ok sent={sent}", 200

            # For each upcoming session in the next hour, send to all confirmed bookings.
            # NOTE: This assumes you have a bookings table with client phone (join via clients).
            with get_session() as s:
                for sess in rows:
                    # fetch client WA numbers attending this session
                    attendees = s.execute(text("""
                        SELECT c.wa_number AS wa
                        FROM bookings b
                        JOIN clients  c ON c.id = b.client_id
                        WHERE b.session_id = :sid AND b.status = 'confirmed'
                    """), {"sid": sess["id"]}).mappings().all()

                    if not attendees:
                        continue

                    hhmm = str(sess["start_time"])[:5]

                    # If you want to use a template (approved), uncomment:
                    # for a in attendees:
                    #     send_whatsapp_template(normalize_wa(a["wa"]),
                    #                            "session_next_hour",
                    #                            [{"type":"text","text": hhmm}])
                    #     sent += 1

                    # Plain text fallback:
                    for a in attendees:
                        send_whatsapp_text(normalize_wa(a["wa"]),
                                           f"⏰ Reminder: Your Pilates session starts at {hhmm} today. Reply CANCEL if you cannot attend.")
                        sent += 1

            logging.info(f"[TASKS] run-reminders sent={sent} [run-reminders] src={src}")
            return f"ok sent={sent}", 200

        except Exception as e:
            logging.exception(e)
            return "error", 500

    @app.post("/tasks/debug-ping-admin")
    def debug_ping_admin():
        """
        Simple connectivity test: send a plain text message to admin.
        """
        try:
            to = normalize_wa(NADINE_WA)
            logging.info(f"[debug] NADINE_WA={repr(NADINE_WA)} (normalized='{to}')")
            if not to:
                return "missing admin", 400
            send_whatsapp_text(to, "Ping from /tasks/debug-ping-admin ✅")
            return "sent", 200
        except Exception as e:
            logging.exception(e)
            return "error", 500
