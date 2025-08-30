# app/tasks.py
import logging
from datetime import date
from .utils import send_whatsapp_text, normalize_wa
from .crud import (
    sessions_next_hour, sessions_tomorrow, sessions_for_day,
    clients_for_session,
)
from .config import NADINE_WA

def register_tasks(app):
    @app.route("/tasks/run-reminders", methods=["POST", "GET"])
    def run_reminders():
        """
        Manual/scheduled trigger:
          1) Next-hour client reminders (rolling window).
          2) Tomorrow client reminders.
          3) Owner daily schedule summary (today).
        """
        sent = 0

        # 1) Next-hour client reminders
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

        # 3) Owner daily schedule (today)
        if NADINE_WA:
            items = sessions_for_day(date.today())
            if items:
                lines = [f"• {s['start_time']} ({s['booked_count']}/{s['capacity']}, {s['status']})" for s in items]
                send_whatsapp_text(normalize_wa(NADINE_WA), "🗓️ Today’s sessions:\n" + "\n".join(lines))
            else:
                send_whatsapp_text(normalize_wa(NADINE_WA), "🗓️ Today: no sessions.")

        logging.info(f"[TASKS] reminders sent={sent}")
        return f"ok sent={sent}", 200
