import logging
from sqlalchemy import text
from .db import get_session
from .utils import send_whatsapp_text, normalize_wa
from .config import NADINE_WA

def _list_upcoming_sessions_today():
    with get_session() as s:
        rows = s.execute(text("""
            SELECT session_date, start_time, capacity, booked_count, status, notes
            FROM sessions
            WHERE session_date = CURRENT_DATE
              AND start_time >= (now() AT TIME ZONE 'UTC')::time
            ORDER BY start_time
        """)).mappings().all()
        return [dict(r) for r in rows]

def _list_sessions_next_hour():
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
    logging.info("[TASKS] registering routes…")
    if not NADINE_WA:
        logging.warning("[TASKS] NADINE_WA not set; admin messages will be skipped.")

    @app.route("/tasks/admin-notify", methods=["GET", "POST"])
    def admin_notify():
        try:
            admin_wa = normalize_wa(NADINE_WA) if NADINE_WA else None
            if not admin_wa:
                return "ok admin-notify skipped (no admin)", 200
            upcoming = _list_upcoming_sessions_today()
            next_hour = _list_sessions_next_hour()
            send_whatsapp_text(admin_wa, _format_day_summary(upcoming))
            send_whatsapp_text(admin_wa, _format_next_hour(next_hour))
            logging.info("[TASKS] admin-notify sent")
            return "ok", 200
        except Exception as e:
            logging.exception("[TASKS] admin-notify failed: %s", e)
            return "error", 500

    @app.route("/tasks/run-reminders", methods=["GET", "POST"])
    def run_reminders():
        try:
            admin_wa = normalize_wa(NADINE_WA) if NADINE_WA else None
            sent = 0
            if admin_wa:
                upcoming = _list_upcoming_sessions_today()
                next_hour = _list_sessions_next_hour()
                send_whatsapp_text(admin_wa, _format_day_summary(upcoming)); sent += 1
                send_whatsapp_text(admin_wa, _format_next_hour(next_hour));  sent += 1
            logging.info(f"[TASKS] run-reminders sent={sent}")
            return f"ok sent={sent}", 200
        except Exception as e:
            logging.exception("[TASKS] run-reminders failed: %s", e)
            return "error", 500

    # tiny diagnostics route so we can prove routes are registered
    @app.route("/tasks/ping", methods=["GET"])
    def tasks_ping():
        return "tasks:ready", 200

    logging.info("[TASKS] endpoints ready: /tasks/admin-notify, /tasks/run-reminders, /tasks/ping")
