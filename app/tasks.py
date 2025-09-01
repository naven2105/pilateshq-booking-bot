import logging
from datetime import date, datetime
from .utils import send_whatsapp_text, normalize_wa
from .crud import sessions_next_hour, sessions_for_day, clients_for_session
from .config import NADINE_WA

def _status_emoji(status: str) -> str:
    st = (status or "").lower()
    if st == "full":
        return "🔒"
    if st == "open":
        return "✅"
    return "•"

def register_tasks(app):
    @app.route("/tasks/run-reminders", methods=["POST", "GET"])
    def run_reminders():
        """
        Manual/cron trigger:
          1) Next-hour client reminders
          2) Tomorrow schedule to clients (if you decide to add later)
          3) Owner daily schedule (today), showing only *upcoming* sessions
        This endpoint is READ-ONLY against sessions/bookings tables.
        """
        sent = 0
        try:
            # 1) Next-hour client reminders (to booked clients)
            for sess in sessions_next_hour():
                for c in clients_for_session(sess["id"]):
                    body = (
                        f"⏰ Reminder: Pilates session at {sess['start_time']} today. "
                        f"Reply CANCEL if you can't make it."
                    )
                    send_whatsapp_text(c["wa_number"], body)
                    sent += 1

            # 3) Owner summary (today). Only show upcoming sessions from now.
            if NADINE_WA:
                now = datetime.utcnow()
                today_items = sessions_for_day(date.today())

                # filter to upcoming
                upcoming = []
                for s in today_items:
                    # combine today's date and start_time to compare with now
                    hhmm = str(s["start_time"])
                    # we don't need exact tz alignment here for testing; it's a simple visual filter
                    if hhmm >= now.strftime("%H:%M:%S"):
                        upcoming.append(s)

                if upcoming:
                    lines = [
                        f"{_status_emoji(s['status'])} {s['start_time']} "
                        f"({s['booked_count']}/{s['capacity']}, {s['status']})"
                        for s in upcoming
                    ]
                    header = f"🗓 Today’s sessions (upcoming: {len(upcoming)})"
                    send_whatsapp_text(normalize_wa(NADINE_WA), header + "\n• " + "\n• ".join(lines))
                else:
                    send_whatsapp_text(normalize_wa(NADINE_WA), "🗓 Today’s sessions (upcoming: 0)\n— none —")

            logging.info(f"[TASKS] reminders sent={sent}")
            return f"ok sent={sent}", 200

        except Exception as e:
            logging.exception(f"[TASKS] run-reminders failed: {e}")
            # Return 500 so Render shows failure clearly
            return "error", 500
