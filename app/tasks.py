# app/tasks.py
"""
Task endpoints for reminders and admin schedule notifications.

Routes (accept both GET and POST so Render Cron or manual curl tests work):
- /tasks/run-hourly   → Admin "next hour" schedule (sent every hour, 06:00–18:00 local via your cron)
- /tasks/run-daily    → Admin "tomorrow's schedule" (sent once daily, e.g., 20:00 local via your cron)
- /tasks/run-reminders → (existing combo) client next-hour reminders, client tomorrow reminders,
                         and admin "today’s schedule" snapshot.

NOTE: Schedule timing is controlled by your Render cron (UTC). Choose UTC times that map to your
desired local time in Johannesburg (UTC+2).
"""

import logging
from datetime import date
from typing import Dict, List

from .utils import send_whatsapp_text, normalize_wa
from .config import NADINE_WA
from .crud import (
    sessions_next_hour,     # → List[Dict]: sessions starting in the next hour (today)
    sessions_tomorrow,      # → List[Dict]: all sessions tomorrow
    sessions_for_day,       # → List[Dict]: all sessions for a given date
    clients_for_session,    # → List[Dict]: clients for a given session_id
)

# ──────────────────────────────────────────────────────────────────────────────
# Helper formatting
# ──────────────────────────────────────────────────────────────────────────────

def _icon_for(status: str, seats_left: int) -> str:
    """
    Map session status to a small emoji:
      - 🔒 for 'full'
      - ✅ for open (has seats)
    """
    if (status or "").lower() == "full":
        return "🔒"
    return "✅" if seats_left > 0 else "🔒"

def _fmt_session_line(sess: Dict) -> str:
    """
    Render one session line like:
      • 09:00:00 (1/6, open) ✅
    """
    start = str(sess.get("start_time"))
    cap = int(sess.get("capacity") or 0)
    booked = int(sess.get("booked_count") or 0)
    status = (sess.get("status") or "").lower()
    seats_left = max(0, cap - booked)
    return f"• {start} ({booked}/{cap}, {status}) {_icon_for(status, seats_left)}"

# ──────────────────────────────────────────────────────────────────────────────
# “Hourly” admin notify: next hour window
# ──────────────────────────────────────────────────────────────────────────────

def _notify_admin_hourly() -> int:
    """
    Sends one message to admin summarizing the *next hour*.
    If there are no upcoming sessions in the next hour, still sends a "no upcoming session" note.
    """
    sent = 0
    if not NADINE_WA:
        logging.info("[TASKS] Hourly admin notify skipped (NADINE_WA not set).")
        return sent

    items = sessions_next_hour() or []
    if items:
        lines = [_fmt_session_line(s) for s in items]
        body = "🕒 *Next hour schedule:*\n" + "\n".join(lines)
    else:
        body = "🕒 *Next hour:* no upcoming session."

    send_whatsapp_text(normalize_wa(NADINE_WA), body)
    sent += 1
    logging.info(f"[TASKS] Hourly admin notify sent={sent}")
    return sent

# ──────────────────────────────────────────────────────────────────────────────
# “Daily” admin notify: tomorrow summary
# ──────────────────────────────────────────────────────────────────────────────

def _notify_admin_daily() -> int:
    """
    Sends one message to admin listing *tomorrow's* sessions.
    Always sends a message (shows “— none —” if empty).
    """
    sent = 0
    if not NADINE_WA:
        logging.info("[TASKS] Daily admin notify skipped (NADINE_WA not set).")
        return sent

    items = sessions_tomorrow() or []
    count = len(items)

    if items:
        lines = [_fmt_session_line(s) for s in items]
        body = f"📆 *Tomorrow’s sessions ({count}):*\n" + "\n".join(lines)
    else:
        body = "📆 *Tomorrow’s sessions (0)*\n— none —"

    send_whatsapp_text(normalize_wa(NADINE_WA), body)
    sent += 1
    logging.info(f"[TASKS] Daily admin notify sent={sent}")
    return sent

# ──────────────────────────────────────────────────────────────────────────────
# Client reminders (existing behavior)
# ──────────────────────────────────────────────────────────────────────────────

def _remind_clients_next_hour() -> int:
    """
    For each session starting in the next hour, send a reminder to each booked client.
    """
    sent = 0
    for sess in sessions_next_hour():
        for c in clients_for_session(sess["id"]):
            body = (
                f"⏰ Reminder: Pilates session at {sess['start_time']} today. "
                "Reply CANCEL if you can't make it."
            )
            send_whatsapp_text(c["wa_number"], body)
            sent += 1
    logging.info(f"[TASKS] client next-hour reminders sent={sent}")
    return sent

def _remind_clients_tomorrow() -> int:
    """
    For each session tomorrow, send a reminder to each booked client.
    """
    sent = 0
    for sess in sessions_tomorrow():
        for c in clients_for_session(sess["id"]):
            body = f"📅 Reminder: Your Pilates session is tomorrow at {sess['start_time']}."
            send_whatsapp_text(c["wa_number"], body)
            sent += 1
    logging.info(f"[TASKS] client tomorrow reminders sent={sent}")
    return sent

# ──────────────────────────────────────────────────────────────────────────────
# Admin “today” schedule snapshot (used by /tasks/run-reminders)
# ──────────────────────────────────────────────────────────────────────────────

def _notify_admin_today_schedule() -> int:
    """
    Sends the admin a "today’s sessions" snapshot (all remaining for the day).
    Always sends a message (shows “— none —” if empty).
    """
    sent = 0
    if not NADINE_WA:
        logging.info("[TASKS] Admin today snapshot skipped (NADINE_WA not set).")
        return sent

    items = sessions_for_day(date.today()) or []
    upcoming = len(items)
    if items:
        lines = [_fmt_session_line(s) for s in items]
        body = f"🗓 Today’s sessions (upcoming: {upcoming})\n" + "\n".join(lines)
    else:
        body = "🗓 Today’s sessions (upcoming: 0)\n— none —"

    send_whatsapp_text(normalize_wa(NADINE_WA), body)
    sent += 1
    logging.info(f"[TASKS] admin today schedule sent={sent}")
    return sent

# ──────────────────────────────────────────────────────────────────────────────
# Flask routes (GET + POST)
# ──────────────────────────────────────────────────────────────────────────────

def register_tasks(app):
    """
    Registers task endpoints on the provided Flask app.
    """

    @app.route("/tasks/run-hourly", methods=["POST", "GET"])
    def run_hourly():
        """
        Send admin "next hour" schedule. Use Render Cron to call this hourly
        (in UTC corresponding to 06:00–18:00 Johannesburg).
        """
        count = _notify_admin_hourly()
        return f"ok sent={count}", 200

    @app.route("/tasks/run-daily", methods=["POST", "GET"])
    def run_daily():
        """
        Send admin "tomorrow's sessions" summary once a day (e.g., 20:00 local).
        """
        count = _notify_admin_daily()
        return f"ok sent={count}", 200

    @app.route("/tasks/run-reminders", methods=["POST", "GET"])
    def run_reminders():
        """
        Existing combined trigger:
          - client next-hour reminders
          - client tomorrow reminders
          - admin today schedule snapshot
        """
        sent = 0
        sent += _remind_clients_next_hour()
        sent += _remind_clients_tomorrow()
        sent += _notify_admin_today_schedule()
        logging.info(f"[TASKS] /tasks/run-reminders total messages sent={sent}")
        return f"ok sent={sent}", 200
