import logging
from datetime import datetime, timedelta, date
from sqlalchemy import text

from .db import get_session
from .utils import send_whatsapp_text, normalize_wa
from .config import NADINE_WA


def _list_upcoming_sessions_today():
    """
    Return today's sessions that are still upcoming (start_time >= now::time)
    as a list of dicts: [{session_date, start_time, capacity, booked_count, status, notes}, ...]
    """
    with get_session() as s:
        rows = s.execute(text("""
            SELECT session_date, start_time, capacity, booked_count, status, notes
            FROM sessions
            WHERE session_date = CURRENT_DATE
              AND start_time >= (now() AT TIME ZONE 'UTC')::time
            ORDER BY session_date, start_time
        """)).mappings().all()
        return [dict(r) for r in rows]


def _list_sessions_next_hour():
    """
    Return sessions that start within the next hour (now .. now+1h) today.
    Useful for the "next hour" admin ping.
    """
    with get_session() as s:
        rows = s.execute(text("""
            SELECT session_date, start_time, capacity, booked_count, status, notes
            FROM sessions
            WHERE session_date = CURRENT_DATE
              AND start_time >= (now() AT TIME ZONE 'UTC')::time
              AND start_time <  ((now() AT TIME ZONE 'UTC') + interval '1 hour')::time
            ORDER BY start_time
        """)).mappings().all()
        return [dict(r) for r in rows]


def _format_day_summary(rows):
    """
    Pretty print today's upcoming sessions for admin.
    Example line: • 09:00 (1/6) ✅
    """
    if not rows:
        return "🗓 Today’s sessions (upcoming: 0)\n— none —"

    lines = []
    for r in rows:
        cap = r.get("capacity") or 0
        booked = r.get("booked_count") or 0
        status = (r.get("status") or "").strip().lower()
        emoji = "🔒" if status == "full" or booked >= cap else "✅"
        hhmm = str(r["start_time"])[:5]
        lines.append(f"• {hhmm} ({booked}/{cap}) {emoji}")

    return f"🗓 Today’s sessions (upcoming: {len(rows)})\n" + "\n".join(lines)


def _format_next_hour(rows):
    """
    Pretty print the 'next hour' block for admin.
    """
    if not rows:
        return "🕒 Next hour: no upcoming session."
    lines = []
    for r in rows:
        cap = r.get("capacity") or 0
        booked = r.get("booked_count") or 0
        hhmm = str(r["start_time"])[:5]
        lines.append(f"• {hhmm} ({booked}/{cap})")
    return "🕒 Next hour:\n" + "\n".join(lines)


def register_tasks(app):
    """
    Mounts task endpoints on the Flask app.
    - /tasks/admin-notify   : For ADMIN only (Nadine) – pushes today's upcoming + next-hour
    - /tasks/run-reminders  : Client reminders (next-hour and tomorrow) + daily admin summary
    Both accept GET and POST so you can test in the browser or curl.
    """
    if not NADINE_WA:
        logging.warning("[TASKS] NADINE_WA not set; admin messages will be skipped.")

    @app.route("/tasks/admin-notify", methods=["GET", "POST"])
    def admin_notify():
        """
        Sends two messages to the admin:
        1) Today's upcoming sessions summary (now onward)
        2) Next-hour sessions block
        Always returns 200 even if no sessions (so cron stays happy).
        """
        try:
            admin_wa = normalize_wa(NADINE_WA) if NADINE_WA else None
            if not admin_wa:
                logging.info("[TASKS] admin-notify skipped; NADINE_WA not configured.")
                return "ok admin-notify skipped (no admin)", 200

            # Build messages
            upcoming = _list_upcoming_sessions_today()
            next_hour = _list_sessions_next_hour()

            body_today = _format_day_summary(upcoming)
            body_next  = _format_next_hour(next_hour)

            # Push to admin
            send_whatsapp_text(admin_wa, body_today)
            send_whatsapp_text(admin_wa, body_next)
            logging.info(f"[TASKS] admin-notify sent (today_upcoming={len(upcoming)}, next_hour={len(next_hour)})")
            return "ok", 200
        except Exception as e:
            logging.exception("[TASKS] admin-notify failed: %s", e)
            return "error", 500

    @app.route("/tasks/run-reminders", methods=["GET", "POST"])
    def run_reminders():
        """
        Minimal version kept for compatibility:
        - Sends the admin today's upcoming summary + next-hour block (same as admin-notify)
        - (Client reminders can be added here later when you enable client messaging)
        """
        try:
            admin_wa = normalize_wa(NADINE_WA) if NADINE_WA else None
            sent = 0

            if admin_wa:
                upcoming = _list_upcoming_sessions_today()
                next_hour = _list_sessions_next_hour()
                send_whatsapp_text(admin_wa, _format_day_summary(upcoming)); sent += 1
                send_whatsapp_text(admin_wa, _format_next_hour(next_hour));  sent += 1
                logging.info(f"[TASKS] run-reminders admin messages sent={sent}")
            else:
                logging.info("[TASKS] run-reminders: admin not configured; skipped.")

            return f"ok sent={sent}", 200
        except Exception as e:
            logging.exception("[TASKS] run-reminders failed: %s", e)
            return "error", 500

    logging.info("[TASKS] endpoints ready: /tasks/admin-notify, /tasks/run-reminders")
