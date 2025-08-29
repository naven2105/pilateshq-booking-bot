# app/tasks.py
import logging
from datetime import date
from .utils import send_whatsapp_text, normalize_wa
from .crud import (
    sessions_next_hour, sessions_tomorrow, sessions_for_day,
    clients_for_session,
)
from .config import NADINE_WA


def _format_session_line(sess: dict) -> str:
    """Build a single line like '• 07:00 — 5/6 booked — Jane, Sipho'."""
    sid = sess["id"]
    time = f"{sess.get('start_time')}"
    cap = int(sess.get("capacity", 0))
    booked = int(sess.get("booked_count", 0))
    # list client names (first names preferred)
    client_rows = clients_for_session(sid)
    names = []
    for c in client_rows:
        nm = (c.get("name") or "").strip() or "(no name)"
        names.append(nm.split()[0] if " " in nm else nm)
    names_str = ", ".join(names) if names else "—"
    return f"• {time} — {booked}/{cap} booked — {names_str}"


def _send_daily_admin_summary():
    """Sends Nadine a concise list of today's sessions and who's in each."""
    if not NADINE_WA:
        logging.warning("[TASKS] NADINE_WA not set; skipping admin summary.")
        return "skipped_no_admin"

    today = date.today()
    items = sessions_for_day(today)

    wa = normalize_wa(NADINE_WA)
    if not items:
        send_whatsapp_text(wa, "🗓️ Today: no sessions.")
        return "ok_none"

    # Sort by start time if not already
    items = sorted(items, key=lambda s: str(s.get("start_time")))
    lines = [_format_session_line(s) for s in items]
    header = f"🗓️ Today’s sessions ({today.isoformat()}):"
    body = header + "\n" + "\n".join(lines)
    send_whatsapp_text(wa, body)
    return "ok_sent"


def register_tasks(app):
    @app.route("/tasks/run-reminders", methods=["POST", "GET"])
    def run_reminders():
        """Manual trigger: next-hour reminders + tomorrow reminders + owner summary."""
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

        # 3) Owner daily schedule (today) — concise times only (legacy)
        if NADINE_WA:
            items = sessions_for_day(date.today())
            if items:
                lines = [f"• {s['start_time']}" for s in sorted(items, key=lambda s: str(s.get('start_time')))]
                send_whatsapp_text(normalize_wa(NADINE_WA), "🗓️ Today’s sessions:\n" + "\n".join(lines))
            else:
                send_whatsapp_text(normalize_wa(NADINE_WA), "🗓️ Today: no sessions.")

        logging.info(f"[TASKS] reminders sent={sent}")
        return f"ok sent={sent}", 200

    @app.route("/tasks/daily-admin-summary", methods=["POST", "GET"])
    def daily_admin_summary():
        """
        Manual/cron trigger: sends Nadine a detailed summary of TODAY with:
          - time, booked/capacity
          - first names of booked clients
        Recommended to run every morning (e.g., 06:45 SAST) via Render Cron.
        """
        try:
            status = _send_daily_admin_summary()
            return f"ok {status}", 200
        except Exception as e:
            logging.exception("[TASKS] daily-admin-summary failed: %s", e)
            return "error", 500
