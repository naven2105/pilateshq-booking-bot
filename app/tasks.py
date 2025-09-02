# app/tasks.py
import logging
from datetime import date, datetime, timedelta, time as dtime
from flask import request

from sqlalchemy import text

from .db import get_session
from .utils import send_whatsapp_text, normalize_wa
from .config import NADINE_WA


# ─────────────────────────────────────────────────────────────────────────────
# Helpers: Source logging
# You can pass ?src=admin-hourly (or any label) so logs identify the trigger
# Also supports a 'daily=1' query param to include the 20:00 daily summary.
# Example:
#   /tasks/admin-notify?src=cron-hourly
#   /tasks/run-reminders?src=cron-hourly&daily=0
#   /tasks/run-reminders?src=cron-20h&daily=1
# ─────────────────────────────────────────────────────────────────────────────
def _log_source(route_name: str) -> str:
    src = (request.args.get("src") or "").strip() or request.headers.get("X-Job", "").strip()
    tag = f"[{route_name}] src={src or 'unknown'}"
    logging.info(tag)
    return tag


# ─────────────────────────────────────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────────────────────────────────────
def _sessions_today_all() -> list[dict]:
    """All sessions for today."""
    with get_session() as s:
        rows = s.execute(text("""
            SELECT id, session_date, start_time, capacity, booked_count, status, COALESCE(notes,'') AS notes
            FROM sessions
            WHERE session_date = CURRENT_DATE
            ORDER BY start_time
        """)).mappings().all()
        return [dict(r) for r in rows]

def _sessions_today_upcoming() -> list[dict]:
    """Today’s sessions from 'now' onwards."""
    with get_session() as s:
        rows = s.execute(text("""
            SELECT id, session_date, start_time, capacity, booked_count, status, COALESCE(notes,'') AS notes
            FROM sessions
            WHERE session_date = CURRENT_DATE
              AND start_time >= (CURRENT_TIME(0))  -- truncate seconds
            ORDER BY start_time
        """)).mappings().all()
        return [dict(r) for r in rows]

def _sessions_next_hour() -> list[dict]:
    """
    Sessions starting within the next hour window (inclusive of now, exclusive of +1h).
    """
    with get_session() as s:
        rows = s.execute(text("""
            SELECT id, session_date, start_time, capacity, booked_count, status, COALESCE(notes,'') AS notes
            FROM sessions
            WHERE session_date = CURRENT_DATE
              AND start_time >= (CURRENT_TIME(0))
              AND start_time <  ((CURRENT_TIME(0)) + INTERVAL '1 hour')
            ORDER BY start_time
        """)).mappings().all()
        return [dict(r) for r in rows]

def _clients_for_session(session_id: int) -> list[dict]:
    """Return wa_number + name for confirmed bookings on a session."""
    with get_session() as s:
        rows = s.execute(text("""
            SELECT c.id, c.wa_number, COALESCE(NULLIF(c.name,''),'(no name)') AS name
            FROM bookings b
            JOIN clients  c ON c.id = b.client_id
            WHERE b.session_id = :sid
              AND (b.status = 'confirmed' OR b.status IS NULL)
        """), {"sid": session_id}).mappings().all()
        return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Formatting helpers
# ─────────────────────────────────────────────────────────────────────────────
def _status_emoji(status: str) -> str:
    st = (status or "").lower()
    if st == "full":
        return "🔒"
    if st == "open":
        return "✅"
    return "•"

def _fmt_session_line(sess: dict) -> str:
    hhmm = str(sess["start_time"])[:5]
    cap = int(sess.get("capacity") or 0)
    bkd = int(sess.get("booked_count") or 0)
    st  = str(sess.get("status") or "")
    emj = _status_emoji(st)
    kind = sess.get("notes") or ""   # e.g., "group", "single", "duo"
    kind_seg = f" • {kind}" if kind else ""
    return f"• {hhmm}{kind_seg} — {bkd}/{cap} {emj}"


# ─────────────────────────────────────────────────────────────────────────────
# /tasks/admin-notify   → Admin-only hourly schedule 06:00–18:00 SAST
# Always sends something, even if there are zero upcoming sessions
# ─────────────────────────────────────────────────────────────────────────────
def register_tasks(app):
    @app.route("/tasks/admin-notify", methods=["POST", "GET"])
    def admin_notify():
        _log_source("admin-notify")
        if not NADINE_WA:
            logging.warning("[ADMIN NOTIFY] NADINE_WA not configured")
            return "ok", 200

        upcoming = _sessions_today_upcoming()
        n = len(upcoming)
        if n == 0:
            send_whatsapp_text(normalize_wa(NADINE_WA), "🗓 Today’s sessions (upcoming: 0)\n— none —")
            logging.info("[TASKS] admin-notify sent (none)")
            return "ok", 200

        lines = [_fmt_session_line(s) for s in upcoming]
        body = "🗓 Today’s sessions (upcoming: {n})\n{lines}".format(
            n=n,
            lines="\n".join(lines)
        )
        send_whatsapp_text(normalize_wa(NADINE_WA), body)
        logging.info("[TASKS] admin-notify sent")
        return "ok", 200

    # ─────────────────────────────────────────────────────────────────────────
    # /tasks/run-reminders → client 1-hour reminders + optional daily admin recap
    # Add ?daily=1 to also push the admin “full-day recap” (used at 20:00 SAST).
    # Without ?daily=1 it will only do client reminders (used for hourly).
    # ─────────────────────────────────────────────────────────────────────────
    @app.route("/tasks/run-reminders", methods=["POST", "GET"])
    def run_reminders():
        tag = _log_source("run-reminders")
        sent = 0

        # 1) Next-hour client reminders
        sessions = _sessions_next_hour()
        for sess in sessions:
            sid = int(sess["id"])
            hhmm = str(sess["start_time"])[:5]
            for c in _clients_for_session(sid):
                body = f"⏰ Reminder: Pilates session at {hhmm} today. Reply CANCEL if you can't make it."
                send_whatsapp_text(c["wa_number"], body)
                sent += 1

        # 2) Optional daily recap for admin (trigger only if daily=1)
        if (request.args.get("daily") or "0").strip() in ("1", "true", "yes"):
            if NADINE_WA:
                today_all = _sessions_today_all()
                upcoming = _sessions_today_upcoming()
                # Choose what to display: the whole day to recap
                lines = [_fmt_session_line(s) for s in today_all] or ["— none —"]
                body = "🗓 Today’s sessions (upcoming: {n})\n{lines}".format(
                    n=len(upcoming),
                    lines="\n".join(lines)
                )
                send_whatsapp_text(normalize_wa(NADINE_WA), body)
                logging.info("[TASKS] daily admin recap sent")

        logging.info(f"[TASKS] run-reminders sent={sent} {tag}")
        return f"ok sent={sent}", 200
