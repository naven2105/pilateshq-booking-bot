from __future__ import annotations
import logging
from datetime import datetime, timedelta, date as _date
from flask import Blueprint, request

from .db import get_session
from sqlalchemy import text

from .config import NADINE_WA, TZ_NAME
from .utils import send_whatsapp_text, normalize_wa

bp = Blueprint("tasks", __name__)

# ──────────────────────────────
# Helpers: SQL blocks
# ──────────────────────────────

def _sessions_next_hour():
    """Return sessions starting in the next whole hour in local time (TZ_NAME)."""
    with get_session() as s:
        rows = s.execute(text(f"""
            WITH now_local AS (
              SELECT (now() AT TIME ZONE 'UTC') AT TIME ZONE :tz AS ts
            ),
            window AS (
              SELECT date_trunc('hour', ts) + interval '1 hour' AS t0,
                     date_trunc('hour', ts) + interval '2 hour' AS t1
              FROM now_local
            )
            SELECT id, session_date, start_time, capacity, booked_count, status, notes
            FROM sessions, window
            WHERE (session_date, start_time) >= (date(t0), time(t0))
              AND (session_date, start_time) <  (date(t1), time(t1))
            ORDER BY start_time
        """), {"tz": TZ_NAME}).mappings().all()
        return [dict(r) for r in rows]

def _sessions_today_upcoming():
    """Today’s sessions from ‘now’ onward in local time."""
    with get_session() as s:
        rows = s.execute(text(f"""
            WITH now_local AS (
              SELECT (now() AT TIME ZONE 'UTC') AT TIME ZONE :tz AS ts
            )
            SELECT id, session_date, start_time, capacity, booked_count, status, notes
            FROM sessions, now_local
            WHERE session_date = date(ts)
              AND start_time >= time(ts)
            ORDER BY start_time
        """), {"tz": TZ_NAME}).mappings().all()
        return [dict(r) for r in rows]

def _sessions_today_full_day():
    """All of today’s sessions in local time."""
    with get_session() as s:
        rows = s.execute(text(f"""
            WITH now_local AS (
              SELECT (now() AT TIME ZONE 'UTC') AT TIME ZONE :tz AS ts
            )
            SELECT id, session_date, start_time, capacity, booked_count, status, notes
            FROM sessions, now_local
            WHERE session_date = date(ts)
            ORDER BY start_time
        """), {"tz": TZ_NAME}).mappings().all()
        return [dict(r) for r in rows]

def _sessions_tomorrow():
    """All of tomorrow’s sessions in local time."""
    with get_session() as s:
        rows = s.execute(text(f"""
            WITH now_local AS (
              SELECT (now() AT TIME ZONE 'UTC') AT TIME ZONE :tz AS ts
            )
            SELECT id, session_date, start_time, capacity, booked_count, status, notes
            FROM sessions, now_local
            WHERE session_date = date(ts) + interval '1 day'
            ORDER BY start_time
        """), {"tz": TZ_NAME}).mappings().all()
        return [dict(r) for r in rows]

# ──────────────────────────────
# Formatters
# ──────────────────────────────

def _fmt_rows(rows):
    if not rows:
        return "— none —"
    out = []
    for r in rows:
        cap = r.get("capacity") or 0
        b   = r.get("booked_count") or 0
        st  = (r.get("status") or "").lower()
        icon = "🔒" if st == "full" or b >= cap else "✅"
        out.append(f"• {r['start_time']} ({b}/{cap}, {st}) {icon}")
    return "\n".join(out)

def _fmt_today_block(upcoming_only: bool):
    items = _sessions_today_upcoming() if upcoming_only else _sessions_today_full_day()
    header = f"🗓 Today’s sessions (upcoming: {len(items)})" if upcoming_only else "🗓 Today’s sessions (full day)"
    return f"{header}\n{_fmt_rows(items)}"

def _fmt_next_hour():
    items = _sessions_next_hour()
    return "🕒 Next hour: \n" + (_fmt_rows(items) if items else "no upcoming session.")

def _fmt_tomorrow_block():
    items = _sessions_tomorrow()
    return "📅 Tomorrow’s sessions\n" + (_fmt_rows(items))

# ──────────────────────────────
# Routes
# ──────────────────────────────

def register_tasks(app):
    app.register_blueprint(bp)

@bp.post("/tasks/admin-notify")
def admin_notify():
    """Admin digest. Called hourly 06:00–18:00 by CRON (and can be triggered manually)."""
    logging.info(f"[admin-notify] src={request.args.get('src') or 'n/a'}")
    admin = normalize_wa(f"+{NADINE_WA}" if NADINE_WA and not NADINE_WA.startswith("+") else NADINE_WA)
    if not admin:
        return "no-admin", 400

    # At 06:00 send full day, otherwise upcoming only (but *always* send something)
    now_utc = datetime.utcnow()
    # We won’t convert here; the SQL already uses TZ for selecting rows. Just format variants.
    body_today = _fmt_today_block(upcoming_only=False if now_utc.hour == 4 else True)
    body_next  = _fmt_next_hour()

    msg = f"{body_today}\n\n{body_next}"
    code, resp = send_whatsapp_text(admin, msg)
    if code and code >= 200 and code < 300:
        logging.info("[TASKS] admin-notify sent")
        return "ok", 200
    logging.error(f"[TASKS] admin-notify failed status={code} resp={resp}")
    return "fail", 500

@bp.post("/tasks/run-reminders")
def run_reminders():
    """
    Client reminders.
      - hourly: send “next hour” reminders (use templates in your booking flow if desired)
      - daily=1 at 20:00: push tomorrow reminders (template recommended)
    Always returns 200 with a small “sent=N” body for CRON visibility.
    """
    logging.info(f"[run-reminders] src={request.args.get('src') or 'n/a'}")
    daily = request.args.get("daily", "0") == "1"
    sent = 0

    if daily:
        # (This route currently only notifies admin; client templates are sent by booking flow or a future loop.)
        admin = normalize_wa(f"+{NADINE_WA}" if NADINE_WA and not NADINE_WA.startswith("+") else NADINE_WA)
        if admin:
            body = _fmt_tomorrow_block()
            code, resp = send_whatsapp_text(admin, body)
            if 200 <= (code or 0) < 300:
                sent += 1
            else:
                logging.error(f"[TASKS] run-reminders daily admin fail status={code} resp={resp}")
        logging.info(f"[TASKS] run-reminders sent={sent} [run-reminders] src={request.args.get('src') or 'n/a'}")
        return f"ok sent={sent}", 200

    # hourly reminders: for now notify admin (client reminders handled elsewhere/templates)
    admin = normalize_wa(f"+{NADINE_WA}" if NADINE_WA and not NADINE_WA.startswith("+") else NADINE_WA)
    if admin:
        rows = _sessions_next_hour()
        if rows:
            times = ", ".join(str(r["start_time"]) for r in rows)
            code, resp = send_whatsapp_text(admin, f"🕒 Next hour sessions: {times}")
        else:
            code, resp = send_whatsapp_text(admin, "🕒 Next hour: no upcoming session.")
        if 200 <= (code or 0) < 300:
            sent += 1
        else:
            logging.error(f"[TASKS] run-reminders hourly admin fail status={code} resp={resp}")

    logging.info(f"[TASKS] run-reminders sent={sent} [run-reminders] src={request.args.get('src') or 'n/a'}")
    return f"ok sent={sent}", 200

@bp.post("/tasks/debug-ping-admin")
def debug_ping_admin():
    """Utility endpoint: confirm we can send a WA message to admin."""
    admin = normalize_wa(f"+{NADINE_WA}" if NADINE_WA and not NADINE_WA.startswith("+") else NADINE_WA)
    logging.info(f"[debug] NADINE_WA='{NADINE_WA}' (normalized='{admin}')")
    if not admin:
        return "no-admin", 400
    code, resp = send_whatsapp_text(admin, "Debug ping ✅")
    if 200 <= (code or 0) < 300:
        return "sent", 200
    return f"fail status={code}", 500