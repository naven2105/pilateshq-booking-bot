# app/tasks.py
import logging
from datetime import date, datetime, time

from .utils import send_whatsapp_text, normalize_wa
from .config import NADINE_WA
from .crud import (
    sessions_next_hour,
    sessions_tomorrow,
    sessions_for_day,
    clients_for_session,
)

def _status_emoji(status: str) -> str:
    s = (status or "").lower()
    if s == "full":
        return "🔒"
    if s == "open":
        return "✅"
    if s == "cancelled":
        return "❌"
    return "•"

def _format_owner_schedule(items, upcoming_only=False) -> str:
    if not items:
        return "🗓 Today’s sessions (upcoming: 0)\n— none —"
    now = datetime.now()
    lines = []
    upcoming = 0
    for s in items:
        sess_dt = datetime.combine(s["session_date"], s["start_time"])
        if upcoming_only and sess_dt < now:
            continue
        if sess_dt >= now:
            upcoming += 1
        em = _status_emoji(s.get("status", "open"))
        lines.append(f"• {s['start_time']} ({s['booked_count']}/{s['capacity']}, {em} {s['status']})")
    if upcoming_only:
        header = f"🗓 Today’s sessions (upcoming: {upcoming})"
    else:
        up_all = sum(1 for s in items if datetime.combine(s["session_date"], s["start_time"]) >= now)
        header = f"🗓 Today’s sessions (upcoming: {up_all})"
    if not lines:
        return f"{header}\n— none —"
    return f"{header}\n" + "\n".join(lines)

def register_tasks(app):
    @app.route("/tasks/run-reminders", methods=["POST", "GET"])
    def run_reminders():
        sent = 0

        # 1) next-hour client reminders
        try:
            for sess in sessions_next_hour():
                if (sess.get("status") or "").lower() == "cancelled":
                    continue
                for c in clients_for_session(sess["id"]):
                    body = f"⏰ Reminder: Pilates session at {sess['start_time']} today. Reply CANCEL if you can't make it."
                    send_whatsapp_text(c["wa_number"], body)
                    sent += 1
        except Exception:
            logging.exception("[TASKS] next-hour reminders failed")

        # 2) tomorrow client reminders (20:00 job)
        try:
            for sess in sessions_tomorrow():
                if (sess.get("status") or "").lower() == "cancelled":
                    continue
                for c in clients_for_session(sess["id"]):
                    body = f"📅 Reminder: Your Pilates session is tomorrow at {sess['start_time']}."
                    send_whatsapp_text(c["wa_number"], body)
                    sent += 1
        except Exception:
            logging.exception("[TASKS] tomorrow reminders failed")

        # 3) owner schedule (full before 06:00; upcoming-only 06:00–18:00)
        try:
            if NADINE_WA:
                now = datetime.now().time()
                upcoming_only = time(6, 0) <= now <= time(18, 0)
                items = sessions_for_day(date.today(), include_cancelled=False)
                msg = _format_owner_schedule(items, upcoming_only=upcoming_only)
                send_whatsapp_text(normalize_wa(NADINE_WA), msg)
        except Exception:
            logging.exception("[TASKS] owner schedule failed")

        logging.info(f"[TASKS] reminders sent={sent}")
        return f"ok sent={sent}", 200
    