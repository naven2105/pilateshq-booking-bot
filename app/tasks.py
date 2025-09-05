# app/tasks.py
from __future__ import annotations

import logging
from typing import List
from sqlalchemy import text
from flask import request

from .db import get_session
from .utils import normalize_wa, send_whatsapp_text  # plain text is simplest & most reliable
from .config import NADINE_WA, TZ_NAME  # e.g. "Africa/Johannesburg"


# ==============================
# Low-level DB helpers (local SA)
# ==============================

def _local_now_hour() -> int:
    """Return current HOUR in local TZ (int 0..23) using DB time."""
    with get_session() as s:
        row = s.execute(
            text("SELECT EXTRACT(HOUR FROM ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz))::int AS h"),
            {"tz": TZ_NAME},
        ).mappings().first()
        return int(row["h"])


def _sessions_next_hour() -> List[dict]:
    """
    Sessions that start within the next hour (local TZ).
    NOTE: we intentionally join via a CTE window to compute [ts, ts+1h).
    """
    with get_session() as s:
        rows = s.execute(
            text(f"""
                WITH now_local AS (
                    SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
                ),
                win AS (
                    SELECT ts, (ts + INTERVAL '1 hour') AS ts_plus FROM now_local
                )
                SELECT s.id, s.session_date, s.start_time, s.capacity, s.booked_count,
                       s.status, COALESCE(s.notes,'') AS notes
                FROM sessions s, win
                WHERE (s.session_date + s.start_time) >= win.ts
                  AND (s.session_date + s.start_time) <  win.ts_plus
                ORDER BY s.start_time
            """),
            {"tz": TZ_NAME},
        ).mappings().all()
        return [dict(r) for r in rows]


def _sessions_today_upcoming() -> List[dict]:
    """Today’s sessions that are still upcoming (local date/time)."""
    with get_session() as s:
        rows = s.execute(
            text("""
                WITH now_local AS (
                    SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
                )
                SELECT s.id, s.session_date, s.start_time, s.capacity, s.booked_count,
                       s.status, COALESCE(s.notes,'') AS notes
                FROM sessions s, now_local
                WHERE s.session_date = (now_local.ts)::date
                  AND s.start_time   >= (now_local.ts)::time
                ORDER BY s.session_date, s.start_time
            """),
            {"tz": TZ_NAME},
        ).mappings().all()
        return [dict(r) for r in rows]


def _sessions_today_full_day() -> List[dict]:
    """All of today’s sessions (local date)."""
    with get_session() as s:
        rows = s.execute(
            text("""
                WITH now_local AS (
                    SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
                )
                SELECT s.id, s.session_date, s.start_time, s.capacity, s.booked_count,
                       s.status, COALESCE(s.notes,'') AS notes
                FROM sessions s, now_local
                WHERE s.session_date = (now_local.ts)::date
                ORDER BY s.session_date, s.start_time
            """),
            {"tz": TZ_NAME},
        ).mappings().all()
        return [dict(r) for r in rows]


def _sessions_tomorrow_full_day() -> List[dict]:
    """All of tomorrow’s sessions (local date)."""
    with get_session() as s:
        rows = s.execute(
            text("""
                WITH now_local AS (
                    SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
                )
                SELECT s.id, s.session_date, s.start_time, s.capacity, s.booked_count,
                       s.status, COALESCE(s.notes,'') AS notes
                FROM sessions s, now_local
                WHERE s.session_date = ((now_local.ts)::date + INTERVAL '1 day')::date
                ORDER BY s.session_date, s.start_time
            """),
            {"tz": TZ_NAME},
        ).mappings().all()
        return [dict(r) for r in rows]


def _attendee_names(session_id: int) -> List[str]:
    """
    Return full names (or a safe fallback) for confirmed attendees of a session.
    We do NOT cap; we’ll split the outbound message into multiple chunks later.
    """
    with get_session() as s:
        rows = s.execute(
            text("""
                SELECT
                  COALESCE(NULLIF(TRIM(c.name), ''), NULL) AS name,
                  COALESCE(NULLIF(TRIM(c.wa_number), ''), NULL) AS wa
                FROM bookings b
                JOIN clients  c ON c.id = b.client_id
                WHERE b.session_id = :sid
                  AND b.status = 'confirmed'
                ORDER BY COALESCE(c.name,''), c.id
            """),
            {"sid": session_id},
        ).mappings().all()

    out = []
    for r in rows:
        if r["name"]:
            out.append(r["name"])
        elif r["wa"]:
            # Safe fallback: show last few digits (privacy-aware)
            wa = r["wa"]
            out.append(f"Client {wa[-4:]}")
        else:
            out.append("Client")
    return out


# ===============
# Text formatting
# ===============

def _status_emoji_row(session: dict) -> str:
    """Return '🔒 full' or '✅ open'."""
    full = (str(session["status"]).lower() == "full") or (session["booked_count"] >= session["capacity"])
    return "🔒 full" if full else "✅ open"


def _wrap_names(names: List[str], indent: str = "   ", max_line_len: int = 120) -> str:
    """
    Produce a multi-line, comma-separated name list without exceeding `max_line_len` per line.
    No truncation; we break into more lines as needed.
    """
    if not names:
        return f"{indent}— none —"

    lines: List[str] = []
    current = indent
    first = True

    for nm in names:
        token = ("" if first else ", ") + nm
        if len(current) + len(token) > max_line_len:
            lines.append(current)
            current = indent + nm  # start new line with name (no comma at start)
            first = False
        else:
            current += token
            first = False

    if current.strip():
        lines.append(current)

    return "\n".join(lines)


def _fmt_rows_simple(rows: List[dict]) -> str:
    """Original compact view: no names, 1 line per session."""
    if not rows:
        return "— none —"
    out = []
    for r in rows:
        seats = f"{r['booked_count']}/{r['capacity']}"
        status = _status_emoji_row(r)
        out.append(f"• {str(r['start_time'])[:5]} ({seats}, {status})")
    return "\n".join(out)


def _fmt_rows_with_names(rows: List[dict]) -> str:
    """
    Names-first view:
    • 09:00 (🔒 full)
       Alice Smith, Bob Jones, …
    We keep capacity off (your preference) and show ALL names, wrapped neatly.
    """
    if not rows:
        return "— none —"

    out_lines: List[str] = []
    for r in rows:
        status = _status_emoji_row(r)
        # Title line (time + status)
        out_lines.append(f"• {str(r['start_time'])[:5]} ({status})")

        # Attendee names
        names = _attendee_names(r["id"])
        # No truncation: wrap across lines
        out_lines.append(_wrap_names(names))

    return "\n".join(out_lines)


def _fmt_today_block(upcoming_only: bool, include_names: bool) -> str:
    items = _sessions_today_upcoming() if upcoming_only else _sessions_today_full_day()
    header = "🗓 Today’s sessions (upcoming)" if upcoming_only else "🗓 Today’s sessions (full day)"
    body = _fmt_rows_with_names(items) if include_names else _fmt_rows_simple(items)
    return f"{header}\n{body}"


# =========================
# Message chunking & sender
# =========================

_MAX_TEXT_CHARS = 3000  # safety margin below any internal limits


def _send_text_chunked(to: str, text_body: str) -> None:
    """
    Send text as 1..N WhatsApp messages so we never exceed size limits.
    Splits on line boundaries to keep messages readable.
    """
    if not text_body:
        return

    lines = text_body.splitlines()
    buf = ""
    for ln in lines:
        # +1 for the '\n' we’ll add when accumulating
        candidate_len = len(buf) + (1 if buf else 0) + len(ln)
        if candidate_len > _MAX_TEXT_CHARS:
            # flush current chunk
            send_whatsapp_text(to, buf)
            buf = ln
        else:
            buf = ln if not buf else (buf + "\n" + ln)

    if buf:
        send_whatsapp_text(to, buf)


# ======
# Routes
# ======

def register_tasks(app):
    @app.post("/tasks/admin-notify")
    def admin_notify():
        """
        Hourly admin summary.
        - At 06:00 local: full-day view.
        - Other hours 06–18: upcoming-only view.
        Always append a “next hour” block (even if none).
        Toggle `?names=1` (default) to include full attendee names with wrap & chunking.
        """
        try:
            src = request.args.get("src", "unknown")
            include_names = request.args.get("names", "1") != "0"
            logging.info(f"[admin-notify] src={src} names={include_names}")

            local_hour = _local_now_hour()
            show_full_day = (local_hour == 6)  # first push of the day

            body_today = _fmt_today_block(upcoming_only=not show_full_day, include_names=include_names)

            # Next hour block (no names for brevity; change to True if you want names here too)
            next_hour = _sessions_next_hour()
            nh_body = _fmt_rows_with_names(next_hour) if include_names else _fmt_rows_simple(next_hour)
            nh_text = "🕒 Next hour:\n" + (nh_body if nh_body.strip() else "— none —")

            msg = f"{body_today}\n\n{nh_text}"

            to = normalize_wa(NADINE_WA)
            if not to:
                logging.warning("[admin-notify] NADINE_WA not configured.")
                return "ok", 200

            _send_text_chunked(to, msg)
            logging.info("[TASKS] admin-notify sent")
            return "ok", 200

        except Exception:
            logging.exception("admin-notify failed")
            return "error", 500

    @app.post("/tasks/run-reminders")
    def run_reminders():
        """
        - daily=0 (default): send client next-hour reminders (if attendees exist).
        - daily=1: admin recap for today (kept for manual tests / fallback).
        """
        try:
            src = request.args.get("src", "unknown")
            daily = request.args.get("daily", "0") == "1"
            logging.info(f"[run-reminders] src={src}")

            if daily:
                today_all = _sessions_today_full_day()
                # For admin recap, you may keep names too—optional:
                body = _fmt_rows_simple(today_all)
                to = normalize_wa(NADINE_WA)
                if to:
                    _send_text_chunked(to, f"🗓 Today’s sessions (full day)\n{body}")
                logging.info(f"[TASKS] run-reminders sent=0 [run-reminders] src={src}")
                return "ok sent=0", 200

            # Hourly client reminders (template/text handled upstream; stick to text for now)
            rows = _sessions_next_hour()
            sent = 0
            if not rows:
                logging.info(f"[TASKS] run-reminders sent={sent} [run-reminders] src={src}")
                return f"ok sent={sent}", 200

            with get_session() as s:
                for sess in rows:
                    attendees = s.execute(
                        text("""
                            SELECT c.wa_number AS wa
                            FROM bookings b
                            JOIN clients  c ON c.id = b.client_id
                            WHERE b.session_id = :sid AND b.status = 'confirmed'
                        """),
                        {"sid": sess["id"]},
                    ).mappings().all()

                    if not attendees:
                        continue

                    hhmm = str(sess["start_time"])[:5]
                    for a in attendees:
                        dest = normalize_wa(a["wa"])
                        if not dest:
                            continue
                        send_whatsapp_text(
                            dest,
                            f"⏰ Reminder: Your Pilates session starts at {hhmm} today. "
                            f"Reply CANCEL if you cannot attend."
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
