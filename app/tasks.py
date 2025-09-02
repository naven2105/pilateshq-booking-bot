# app/tasks.py
import logging
from datetime import date, timedelta
from flask import request

from .utils import send_whatsapp_text, normalize_wa
from .config import NADINE_WA
from .crud import (
    # client-facing reminders
    sessions_next_hour,        # list of sessions starting in next ~60 mins
    sessions_tomorrow,         # list of all sessions tomorrow
    clients_for_session,       # clients for a given session_id

    # admin summaries
    sessions_for_day,          # list of all sessions for a given date
)

def _fmt_admin_lines(sessions):
    """
    Build pretty admin lines with occupancy and emoji status.
    Input rows must contain: start_time, capacity, booked_count, status.
    """
    lines = []
    for s in sessions:
        cap = s.get("capacity") or 0
        booked = s.get("booked_count") or 0
        status = (s.get("status") or "").lower()
        # emojis: open → ✅, full → 🔒, otherwise ➖
        emoji = "✅" if status == "open" else ("🔒" if status == "full" else "➖")
        lines.append(f"• {s['start_time']} ({booked}/{cap}, {status}) {emoji}")
    return lines

def register_tasks(app):
    @app.route("/tasks/run-reminders", methods=["POST", "GET"])
    def run_reminders():
        """
        1) Client reminders:
           - Next hour reminders (today)
           - Tomorrow reminders (once per day run)

        2) Admin daily summary at 20:00 job:
           - Shows **tomorrow's schedule** (NEXT-DAY PREVIEW)
             This replaces the old 'today recap' behavior.
        """
        sent = 0

        # -- 1) Next-hour client reminders
        try:
            for sess in sessions_next_hour():
                for c in clients_for_session(sess["id"]):
                    body = f"⏰ Reminder: Pilates session at {sess['start_time']} today. Reply CANCEL if you can't make it."
                    send_whatsapp_text(c["wa_number"], body)
                    sent += 1
        except Exception as e:
            logging.exception("[TASKS] next-hour reminders failed: %s", e)

        # -- 2) Tomorrow client reminders (evening job usually)
        try:
            for sess in sessions_tomorrow():
                for c in clients_for_session(sess["id"]):
                    body = f"📅 Reminder: Your Pilates session is tomorrow at {sess['start_time']}."
                    send_whatsapp_text(c["wa_number"], body)
                    sent += 1
        except Exception as e:
            logging.exception("[TASKS] tomorrow reminders failed: %s", e)

        # -- 3) Admin next-day preview (20:00 SAST CRON calls this endpoint)
        try:
            if NADINE_WA:
                wa_admin = normalize_wa(NADINE_WA)
                target_day = date.today() + timedelta(days=1)  # <<< CHANGED: always show TOMORROW
                items = sessions_for_day(target_day)

                if items:
                    lines = _fmt_admin_lines(items)
                    header = f"🗓 Tomorrow’s schedule ({target_day.isoformat()}) – total: {len(items)}"
                    send_whatsapp_text(wa_admin, header + "\n" + "\n".join(lines))
                else:
                    send_whatsapp_text(wa_admin, f"🗓 Tomorrow ({target_day.isoformat()}): no sessions.")
        except Exception as e:
            logging.exception("[TASKS] admin next-day preview failed: %s", e)

        logging.info(f"[TASKS] run-reminders sent={sent}")
        return f"ok sent={sent}", 200

    @app.route("/tasks/admin-notify", methods=["POST"])
    def admin_notify():
        """
        Hourly **admin** tick (06:00–18:00 CRON):
        - Shows today’s **upcoming** sessions from 'now' onward.
        - Sends a 'no upcoming' line if none (so admin still gets a ping).
        """
        try:
            if not NADINE_WA:
                return "ok", 200

            wa_admin = normalize_wa(NADINE_WA)
            today = date.today()
            items = sessions_for_day(today)

            # Filter to upcoming only (keep it simple; DB already returns ordered)
            # If you prefer filtering by time in SQL, move this into a CRUD helper.
            from datetime import datetime
            now_hhmm = datetime.now().time()

            upcoming = [s for s in items if s["start_time"] >= now_hhmm]
            if upcoming:
                lines = _fmt_admin_lines(upcoming)
                header = f"🗓 Today’s sessions (upcoming: {len(upcoming)})"
                send_whatsapp_text(wa_admin, header + "\n" + "\n".join(lines))
            else:
                send_whatsapp_text(wa_admin, "🗓 Today’s sessions (upcoming: 0)\n— none —")

            # Also include a tiny “next hour” signal (optional)
            # If you prefer to keep this quiet, feel free to remove.
            from .crud import sessions_next_hour
            nx = list(sessions_next_hour())
            if nx:
                lines = _fmt_admin_lines(nx)
                send_whatsapp_text(wa_admin, "🕒 Next hour:\n" + "\n".join(lines))
            else:
                send_whatsapp_text(wa_admin, "🕒 Next hour: no upcoming session.")
        except Exception as e:
            logging.exception("[TASKS] admin-notify failed: %s", e)
        logging.info("[TASKS] admin-notify sent")
        return "ok", 200
