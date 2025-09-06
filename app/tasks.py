from __future__ import annotations
import logging
from sqlalchemy import text
from flask import request
from .db import get_session
from .utils import normalize_wa, send_whatsapp_text
from .config import NADINE_WA, TZ_NAME

def _sessions_next_hour():
    with get_session() as s:
        rows = s.execute(
            text("""
                WITH now_local AS (
                    SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
                ),
                win AS (
                    SELECT ts, (ts + INTERVAL '1 hour') AS ts_plus FROM now_local
                )
                SELECT id, session_date, start_time, capacity, booked_count, status, COALESCE(notes,'') AS notes
                FROM sessions, win
                WHERE (session_date + start_time) >= win.ts
                  AND (session_date + start_time) <  win.ts_plus
                ORDER BY start_time
            """),
            {"tz": TZ_NAME},
        ).mappings().all()
        return [dict(r) for r in rows]

def _sessions_today(upcoming_only: bool):
    with get_session() as s:
        if upcoming_only:
            sql = """
                WITH now_local AS (SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts)
                SELECT id, session_date, start_time, capacity, booked_count, status, COALESCE(notes,'') AS notes
                FROM sessions, now_local
                WHERE session_date = (now_local.ts)::date AND start_time >= (now_local.ts)::time
                ORDER BY session_date, start_time
            """
        else:
            sql = """
                WITH now_local AS (SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts)
                SELECT id, session_date, start_time, capacity, booked_count, status, COALESCE(notes,'') AS notes
                FROM sessions, now_local
                WHERE session_date = (now_local.ts)::date
                ORDER BY session_date, start_time
            """
        rows = s.execute(text(sql), {"tz": TZ_NAME}).mappings().all()
        return [dict(r) for r in rows]

def _fmt_rows(rows):
    if not rows:
        return "— none —"
    out = []
    for r in rows:
        seats = f"{r['booked_count']}/{r['capacity']}"
        full = (str(r["status"]).lower() == "full") or (r["booked_count"] >= r["capacity"])
        status = "🔒 full" if full else "✅ open"
        out.append(f"• {str(r['start_time'])[:5]} ({seats}, {status})")
    return "\n".join(out)

def _fmt_today_block(upcoming_only: bool):
    items = _sessions_today(upcoming_only)
    header = f"🗓 Today’s sessions (upcoming: {len(items)})" if upcoming_only else "🗓 Today’s sessions (full day)"
    return f"{header}\n{_fmt_rows(items)}"

def register_tasks(app):
    # idempotent guard
    if getattr(app, "_tasks_registered", False):
        logging.debug("[tasks] routes already registered; skipping")
        return
    app._tasks_registered = True

    @app.post("/tasks/admin-notify")
    def admin_notify():
        try:
            src = request.args.get("src", "unknown")
            logging.info(f"[admin-notify] src={src}")
            with get_session() as s:
                hour_utc = s.execute(text("SELECT EXTRACT(HOUR FROM now())::int AS h")).mappings().first()["h"]
            body_today = _fmt_today_block(upcoming_only=False if hour_utc == 4 else True)
            next_hour = _sessions_next_hour()
            nh_text = "🕒 Next hour:\n" + _fmt_rows(next_hour) if next_hour else "🕒 Next hour: no upcoming session."
            msg = f"{body_today}\n\n{nh_text}"
            to = normalize_wa(NADINE_WA)
            if to:
                send_whatsapp_text(to, msg)
                logging.info("[TASKS] admin-notify sent")
            else:
                logging.warning("[admin-notify] NADINE_WA not configured")
            return "ok", 200
        except Exception:
            logging.exception("admin-notify failed")
            return "error", 500

    @app.post("/tasks/run-reminders")
    def run_reminders():
        try:
            src = request.args.get("src", "unknown")
            daily = request.args.get("daily", "0") == "1"
            logging.info(f"[run-reminders] src={src}")
            if daily:
                today_all = _sessions_today(upcoming_only=False)
                header = f"🗓 Today’s sessions (upcoming: {len([r for r in today_all if r['booked_count'] < r['capacity']])})"
                body = _fmt_rows(today_all)
                to = normalize_wa(NADINE_WA)
                if to:
                    send_whatsapp_text(to, f"{header}\n{body}")
                logging.info(f"[TASKS] run-reminders sent=0 [run-reminders] src={src}")
                return "ok sent=0", 200

            rows = _sessions_next_hour()
            sent = 0
            if not rows:
                logging.info(f"[TASKS] run-reminders sent={sent} [run-reminders] src={src}")
                return f"ok sent={sent}", 200

            from sqlalchemy import text as _t  # local alias
            with get_session() as s:
                for sess in rows:
                    attendees = s.execute(_t("""
                        SELECT c.wa_number AS wa
                        FROM bookings b
                        JOIN clients  c ON c.id = b.client_id
                        WHERE b.session_id = :sid AND b.status = 'confirmed'
                    """), {"sid": sess["id"]}).mappings().all()
                    if not attendees:
                        continue
                    hhmm = str(sess["start_time"])[:5]
                    for a in attendees:
                        send_whatsapp_text(
                            normalize_wa(a["wa"]),
                            f"⏰ Reminder: Your Pilates session starts at {hhmm} today. Reply CANCEL if you cannot attend."
                        )
                        sent += 1
            logging.info(f"[TASKS] run-reminders sent={sent} [run-reminders] src={src}")
            return f"ok sent={sent}", 200
        except Exception:
            logging.exception("run-reminders failed")
            return "error", 500

    @app.post("/tasks/debug-ping-admin")
    def debug_ping_admin():
        try:
            to = normalize_wa(NADINE_WA)
            logging.info(f"[debug] NADINE_WA={repr(NADINE_WA)} (normalized='{to}')")
            if not to:
                return "missing admin", 400
            send_whatsapp_text(to, "Ping from /tasks/debug-ping-admin ✅")
            return "sent", 200
        except Exception:
            logging.exception("debug-ping-admin failed")
            return "error", 500
