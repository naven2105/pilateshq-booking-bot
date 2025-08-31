# app/tasks.py
import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from .utils import send_whatsapp_text, normalize_wa
from .crud import (
    sessions_next_hour,
    sessions_tomorrow,
    sessions_for_day_all,
    sessions_for_day_upcoming,
    clients_for_session,
)
from .config import NADINE_WA

ZA = ZoneInfo("Africa/Johannesburg")

STATUS_EMOJI = {
    "open": "✅",
    "full": "🔒",
}

def _fmt_session_line(s: dict) -> str:
    """
    Show one session line like:
    • 09:00:00 (1/6, ✅ open)
    """
    cap    = int(s.get("capacity") or 0)
    booked = int(s.get("booked_count") or 0)
    st     = (s.get("status") or "").lower()
    em     = STATUS_EMOJI.get(st, "")
    return f"• {s['start_time']} ({booked}/{cap}, {em} {st})".strip()

def _send_admin_today_summary(upcoming_only: bool = True) -> bool:
    """Send Nadine a compact list of today's sessions: full day (06:00) or upcoming only (later)."""
    if not NADINE_WA:
        return False
    today = date.today()
    items = sessions_for_day_upcoming(today) if upcoming_only else sessions_for_day_all(today)
    count = len(items)
    header = f"🗓️ Today’s sessions (upcoming: {count})" if upcoming_only else f"🗓️ Today’s sessions (all: {count})"
    if items:
        lines = [_fmt_session_line(s) for s in items]
        send_whatsapp_text(normalize_wa(NADINE_WA), header + "\n" + "\n".join(lines))
    else:
        send_whatsapp_text(normalize_wa(NADINE_WA), header + "\n— none —")
    return True

def _send_admin_tomorrow_summary() -> bool:
    """Send Nadine tomorrow's full schedule with count header."""
    if not NADINE_WA:
        return False
    items = sessions_tomorrow()
    count = len(items)
    header = f"📅 Tomorrow’s sessions ({count})"
    if items:
        lines = [_fmt_session_line(s) for s in items]
        send_whatsapp_text(normalize_wa(NADINE_WA), header + "\n" + "\n".join(lines))
    else:
        send_whatsapp_text(normalize_wa(NADINE_WA), header + "\n— none —")
    return True

def _send_admin_hourly_window() -> bool:
    """Send Nadine a narrow 'next-hour' view (with emojis), or 'none' if empty."""
    if not NADINE_WA:
        return False
    items = sessions_next_hour()
    if items:
        lines = [_fmt_session_line(s) for s in items]
        send_whatsapp_text(normalize_wa(NADINE_WA), "🕒 Next hour:\n" + "\n".join(lines))
    else:
        send_whatsapp_text(normalize_wa(NADINE_WA), "🕒 Next hour: no upcoming session.")
    return True

def register_tasks(app):
    @app.route("/tasks/run-reminders", methods=["POST", "GET"])
    def run_reminders():
        """
        Manual/cron trigger:
          1) Next-hour client reminders
          2) Tomorrow client reminders
          3) Admin summary for today (upcoming-only by default)
        """
        sent = 0

        # 1) Next-hour client reminders (per session → per client)
        for sess in sessions_next_hour():
            for c in clients_for_session(sess["id"]):
                body = f"⏰ Reminder: Pilates session at {sess['start_time']} today. Reply CANCEL if you can't make it."
                send_whatsapp_text(c["wa_number"], body)
                sent += 1

        # 2) Tomorrow reminders
        for sess in sessions_tomorrow():
            for c in clients_for_session(sess["id"]):
                body = f"📅 Reminder: Your Pilates session is tomorrow at {sess['start_time']}."
                send_whatsapp_text(c["wa_number"], body)
                sent += 1

        # 3) Admin daily schedule (default: upcoming only)
        _send_admin_today_summary(upcoming_only=True)

        logging.info(f"[TASKS] reminders sent={sent}")
        return f"ok sent={sent}", 200

    @app.route("/tasks/admin-notify", methods=["POST", "GET"])
    def admin_notify():
        """
        Single endpoint you can call hourly via Cron.
        Behavior (Africa/Johannesburg time):
          - At 06:00 (hr == 6): send FULL-DAY summary for today.
          - From 07:00 to 19:59 (7 ≤ hr < 20): send UPCOMING-ONLY summary for today + 'next-hour' window.
          - At 20:00 (hr == 20, minute == 0): send TOMORROW summary.
          - Other hours: do nothing (idle).
        """
        now_za = datetime.now(ZA)
        hr = now_za.hour
        mn = now_za.minute

        if hr == 6:
            _send_admin_today_summary(upcoming_only=False)
            logging.info(f"[ADMIN-NOTIFY] full-day summary sent at {now_za.isoformat()}")
            return "ok full-day", 200

        if 7 <= hr < 20:
            _send_admin_today_summary(upcoming_only=True)
            _send_admin_hourly_window()
            logging.info(f"[ADMIN-NOTIFY] upcoming+hourly sent at {now_za.isoformat()}")
            return "ok upcoming+hourly", 200

        if hr == 20 and mn == 0:
            _send_admin_tomorrow_summary()
            logging.info(f"[ADMIN-NOTIFY] tomorrow summary sent at {now_za.isoformat()}")
            return "ok tomorrow", 200

        logging.info(f"[ADMIN-NOTIFY] idle at {now_za.isoformat()}")
        return "ok idle", 200
