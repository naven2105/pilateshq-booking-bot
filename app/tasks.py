# app/tasks.py
import logging
from datetime import datetime, date, time
from typing import List, Dict

from .utils import send_whatsapp_text, normalize_wa
from .crud import (
    sessions_next_hour,     # returns list of sessions in the next hour window
    sessions_tomorrow,      # returns list of sessions for tomorrow
    sessions_for_day,       # returns list of sessions for a given date
    clients_for_session,    # returns list of clients booked on a session_id
)
from .config import NADINE_WA


def _fmt_session_line(sess: Dict) -> str:
    """
    Render a one-line summary for admin schedule messages.
    Expects keys: start_time, capacity, booked_count, status, notes (optional).
    """
    start = str(sess["start_time"])
    cap = int(sess.get("capacity", 0))
    booked = int(sess.get("booked_count", 0))
    status = (sess.get("status") or "").lower()
    badge = "✅ open" if status == "open" else "🔒 full" if status == "full" else status or "—"
    note = sess.get("notes") or ""
    note_part = f" • {note}" if note else ""
    return f"• {start} ({booked}/{cap}, {badge}){note_part}"


def _send_admin_hourly(now: datetime) -> int:
    """
    Send hourly 'next-hour' update to admin between 06:00 and 18:00 inclusive.
    Always sends a message (even if no upcoming session).
    Returns number of messages sent (0 or 1).
    """
    if not NADINE_WA:
        logging.info("[TASKS] _send_admin_hourly: NADINE_WA not configured; skipping.")
        return 0

    hour = now.time()
    if not (time(6, 0) <= hour <= time(18, 0)):
        logging.info(f"[TASKS] _send_admin_hourly: outside 06:00–18:00 (now={hour}); skipping.")
        return 0

    upcoming = sessions_next_hour() or []
    if upcoming:
        lines = [_fmt_session_line(s) for s in upcoming]
        body = "🕒 Next hour:\n" + "\n".join(lines)
    else:
        body = "🕒 Next hour: no upcoming session."

    send_whatsapp_text(normalize_wa(NADINE_WA), body)
    logging.info(f"[TASKS] Sent hourly admin update (count={len(upcoming)})")
    return 1


def _send_admin_daily_20h(now: datetime) -> int:
    """
    At exactly 20:00, send 'tomorrow schedule' to admin.
    Sends a message even if there are no sessions tomorrow.
    Returns number of messages sent (0 or 1).
    """
    if not NADINE_WA:
        logging.info("[TASKS] _send_admin_daily_20h: NADINE_WA not configured; skipping.")
        return 0

    if not (now.hour == 20 and 0 <= now.minute < 60):
        logging.info(f"[TASKS] _send_admin_daily_20h: not 20h (now={now.time()}); skipping.")
        return 0

    items = sessions_tomorrow() or []
    if items:
        lines = [_fmt_session_line(s) for s in items]
        body = "🗓 Tomorrow’s sessions:\n" + "\n".join(lines)
    else:
        body = "🗓 Tomorrow’s sessions\n— none —"

    send_whatsapp_text(normalize_wa(NADINE_WA), body)
    logging.info(f"[TASKS] Sent 20h admin daily (count={len(items)})")
    return 1


def _send_admin_today_overview(now: datetime) -> int:
    """
    Optional: if you want a 'today overview' when the endpoint is triggered
    (kept from earlier behavior). We keep it, but it won’t spam—just one message
    showing upcoming count based on current time.
    """
    if not NADINE_WA:
        return 0

    today = date.today()
    items = sessions_for_day(today) or []

    # Only show upcoming slots (>= current time) during the day; else show all at 06:00.
    show_all = now.hour == 6  # at the start of the day, show the full day view
    if show_all:
        filtered: List[Dict] = items
    else:
        now_t = now.time()
        filtered = [s for s in items if str(s["start_time"]) >= str(now_t)]

    count = len(filtered)
    if count:
        lines = [_fmt_session_line(s) for s in filtered]
        body = f"🗓 Today’s sessions (upcoming: {count})\n" + "\n".join(lines)
    else:
        body = "🗓 Today’s sessions (upcoming: 0)\n— none —"

    send_whatsapp_text(normalize_wa(NADINE_WA), body)
    logging.info(f"[TASKS] Sent today overview (upcoming={count})")
    return 1


def register_tasks(app):
    @app.route("/tasks/run-reminders", methods=["POST", "GET"])
    def run_reminders():
        """
        Manual/CRON trigger:
          - Hourly admin 'next-hour' update (06:00–18:00) — ALWAYS sends, even if none.
          - Daily admin 20:00 'tomorrow schedule' — ALWAYS sends, even if none.
          - Client reminders remain as originally implemented (if you want them here,
            you can add them below similarly).
        """
        sent = 0
        now = datetime.now()

        # 1) Hourly admin update (only 06–18; always sends a message)
        sent += _send_admin_hourly(now)

        # 2) Daily 20h admin 'tomorrow' schedule (always sends a message)
        sent += _send_admin_daily_20h(now)

        # 3) (Optional) Today overview for admin (kept from earlier behavior).
        #    If you prefer not to send this every call, you can guard it by hour.
        #    For clarity we’ll send it once at 06:00 (set in _send_admin_today_overview).
        if now.hour == 6:
            sent += _send_admin_today_overview(now)

        logging.info(f"[TASKS] run-reminders completed; messages sent={sent}")
        return f"ok sent={sent}", 200
