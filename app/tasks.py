# app/tasks.py
import logging
from typing import List, Dict, Any
from flask import request
from sqlalchemy import text

from .db import get_session
from .utils import send_whatsapp_text, normalize_wa
from .config import NADINE_WA

# ──────────────────────────────────────────────────────────────────────────────
# SQL helpers (local, to avoid missing-import errors)
# All time logic uses Africa/Johannesburg local time to match studio hours.
# ──────────────────────────────────────────────────────────────────────────────

def _rows_to_dicts(rows) -> List[Dict[str, Any]]:
    return [dict(r) for r in rows]

def _sessions_today_upcoming() -> List[Dict[str, Any]]:
    """All sessions today at/after 'now' (SAST), ordered."""
    with get_session() as s:
        rows = s.execute(text("""
            WITH now_local AS (
                SELECT (NOW() AT TIME ZONE 'Africa/Johannesburg') AS ts
            )
            SELECT id, session_date, start_time, capacity, booked_count, status, notes
            FROM sessions, now_local
            WHERE session_date = (now_local.ts)::date
              AND start_time >= (now_local.ts)::time
            ORDER BY session_date, start_time
        """)).mappings().all()
        return _rows_to_dicts(rows)

def _sessions_today_full_day() -> List[Dict[str, Any]]:
    """All sessions today (SAST), regardless of time."""
    with get_session() as s:
        rows = s.execute(text("""
            WITH now_local AS (
                SELECT (NOW() AT TIME ZONE 'Africa/Johannesburg') AS ts
            )
            SELECT id, session_date, start_time, capacity, booked_count, status, notes
            FROM sessions, now_local
            WHERE session_date = (now_local.ts)::date
            ORDER BY session_date, start_time
        """)).mappings().all()
        return _rows_to_dicts(rows)

def _sessions_next_hour() -> List[Dict[str, Any]]:
    """Sessions starting within the next hour from 'now' (SAST)."""
    with get_session() as s:
        rows = s.execute(text("""
            WITH now_local AS (
                SELECT (NOW() AT TIME ZONE 'Africa/Johannesburg') AS ts
            ),
            bounds AS (
                SELECT (ts)::date AS d,
                       (DATE_TRUNC('minute', ts))::time AS t_now,
                       (DATE_TRUNC('minute', ts) + INTERVAL '1 hour')::time AS t_next
                FROM now_local
            )
            SELECT id, session_date, start_time, capacity, booked_count, status, notes
            FROM sessions, bounds
            WHERE session_date = bounds.d
              AND start_time >= bounds.t_now
              AND start_time <  bounds.t_next
            ORDER BY start_time
        """)).mappings().all()
        return _rows_to_dicts(rows)

def _sessions_tomorrow() -> List[Dict[str, Any]]:
    """All sessions tomorrow (SAST)."""
    with get_session() as s:
        rows = s.execute(text("""
            WITH now_local AS (
                SELECT (NOW() AT TIME ZONE 'Africa/Johannesburg')::date + 1 AS d
            )
            SELECT id, session_date, start_time, capacity, booked_count, status, notes
            FROM sessions, now_local
            WHERE session_date = now_local.d
            ORDER BY start_time
        """)).mappings().all()
        return _rows_to_dicts(rows)

def _clients_for_session(session_id: int) -> List[Dict[str, Any]]:
    """Confirmed clients for a session."""
    with get_session() as s:
        rows = s.execute(text("""
            SELECT c.id, c.wa_number, COALESCE(NULLIF(c.name,''), '(no name)') AS name
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            WHERE b.session_id = :sid
              AND b.status = 'confirmed'
            ORDER BY c.name
        """), {"sid": session_id}).mappings().all()
        return _rows_to_dicts(rows)

# ──────────────────────────────────────────────────────────────────────────────
# Formatting helpers
# ──────────────────────────────────────────────────────────────────────────────

def _fmt_line(sess: Dict[str, Any]) -> str:
    """One session line with emoji status and capacity info."""
    cap = sess.get("capacity") or 0
    bk  = sess.get("booked_count") or 0
    status = (sess.get("status") or "").lower()
    emoji = "🔒" if status == "full" or bk >= cap else "✅"
    return f"• {sess['start_time']} ({bk}/{cap}, {status}) {emoji}"

def _fmt_today_block(upcoming_only: bool) -> str:
    items = _sessions_today_upcoming() if upcoming_only else _sessions_today_full_day()
    if not items:
        header = "🗓 Today’s sessions (upcoming: 0)"
        return header + "\n— none —"
    upcoming_count = len(items) if upcoming_only else len([i for i in items if i["status"] in ("open","full","cancelled","closed")])
    header = f"🗓 Today’s sessions (upcoming: {upcoming_count})"
    lines = [header] + [_fmt_line(s) for s in items]
    return "\n".join(lines)

def _fmt_next_hour_block() -> str:
    items = _sessions_next_hour()
    if not items:
        return "🕒 Next hour: no upcoming session."
    lines = ["🕒 Next hour:"] + [_fmt_line(s) for s in items]
    return "\n".join(lines)

# ──────────────────────────────────────────────────────────────────────────────
# Task routes
# Register these on the Flask app in app.main
# ──────────────────────────────────────────────────────────────────────────────

def register_tasks(app):
    @app.route("/tasks/debug-ping-admin", methods=["GET", "POST"])
    def debug_ping_admin():
        """
        Minimal reachability test:
        - Logs the current NADINE_WA value
        - Sends a single text to admin
        """
        logging.info(f"[debug] NADINE_WA='{NADINE_WA}' (normalized='{normalize_wa(NADINE_WA)}')")
        if not NADINE_WA:
            return "NADINE_WA not set", 500
        send_whatsapp_text(NADINE_WA, "🔔 Debug: admin reachable?")
        return "sent", 200

    @app.route("/tasks/admin-notify", methods=["POST", "GET"])
    def admin_notify():
        """
        Admin-focused ping:
        - Always sends *two* blocks:
            1) Today’s upcoming sessions (from now; SAST)
            2) Next-hour window summary
        - Sends even if empty (shows '— none —' and 'no upcoming session')
        """
        src = request.args.get("src", "manual")
        logging.info(f"[admin-notify] src={src}")

        if not NADINE_WA:
            logging.warning("[admin-notify] NADINE_WA not set; skipping send.")
            return "ok", 200

        # 1) Today’s (upcoming from now)
        body_today = _fmt_today_block(upcoming_only=True)
        send_whatsapp_text(NADINE_WA, body_today)

        # 2) Next-hour window
        body_hour = _fmt_next_hour_block()
        send_whatsapp_text(NADINE_WA, body_hour)

        logging.info("[TASKS] admin-notify sent")
        return "ok", 200

    @app.route("/tasks/run-reminders", methods=["POST", "GET"])
    def run_reminders():
        """
        Client reminders + admin daily recap (optional):
        - daily=0 (default): only client next-hour + client tomorrow reminders
        - daily=1: also send an admin 'Today’s sessions (full-day or upcoming)' + 'Next hour' block
        """
        src = request.args.get("src", "manual")
        daily = (request.args.get("daily", "0") == "1")
        logging.info(f"[run-reminders] src={src}")

        sent = 0

        # 1) Next-hour client reminders
        for sess in _sessions_next_hour():
            for c in _clients_for_session(sess["id"]):
                body = f"⏰ Reminder: Pilates session at {sess['start_time']} today. Reply CANCEL if you can't make it."
                send_whatsapp_text(c["wa_number"], body)
                sent += 1

        # 2) Tomorrow client reminders
        for sess in _sessions_tomorrow():
            for c in _clients_for_session(sess["id"]):
                body = f"📅 Reminder: Your Pilates session is tomorrow at {sess['start_time']}."
                send_whatsapp_text(c["wa_number"], body)
                sent += 1

        # 3) Optional admin daily recap
        if daily and NADINE_WA:
            body_today = _fmt_today_block(upcoming_only=False)
            send_whatsapp_text(normalize_wa(NADINE_WA), body_today)
            send_whatsapp_text(normalize_wa(NADINE_WA), _fmt_next_hour_block())

        logging.info(f"[TASKS] run-reminders sent={sent} [run-reminders] src={src}")
        return f"ok sent={sent}", 200
