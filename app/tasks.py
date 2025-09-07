# app/tasks.py
from __future__ import annotations

import logging
from flask import request
from sqlalchemy import text

from .db import get_session
from .utils import normalize_wa, send_whatsapp_text
from .config import NADINE_WA, TZ_NAME


# ──────────────────────────────────────────────────────────────────────────────
# SQL helpers (Africa/Johannesburg local via AT TIME ZONE)
# NOTE: do NOT use CTE name "window" (reserved in PostgreSQL). Use "win".
# Names are aggregated via DISTINCT+ORDER subselect to avoid PG DISTINCT/ORDER rule.
# ──────────────────────────────────────────────────────────────────────────────

def _rows_next_hour():
    """
    Sessions starting within the next hour (local time), with aggregated names.
    """
    sql = text("""
        WITH now_local AS (
            SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
        ),
        win AS (
            SELECT ts, (ts + INTERVAL '1 hour') AS ts_plus FROM now_local
        )
        SELECT
            s.id,
            s.session_date,
            s.start_time,
            s.capacity,
            s.booked_count,
            s.status,
            COALESCE(s.notes, '') AS notes,
            COALESCE((
                SELECT STRING_AGG(nm, ', ' ORDER BY nm)
                FROM (
                    SELECT DISTINCT COALESCE(c2.name, '') AS nm
                    FROM bookings b2
                    JOIN clients  c2 ON c2.id = b2.client_id
                    WHERE b2.session_id = s.id
                      AND b2.status = 'confirmed'
                ) d
            ), '') AS names
        FROM sessions s
        CROSS JOIN win
        WHERE (s.session_date + s.start_time) >= win.ts
          AND (s.session_date + s.start_time) <  win.ts_plus
        ORDER BY s.start_time;
    """)
    with get_session() as s:
        return [dict(r) for r in s.execute(sql, {"tz": TZ_NAME}).mappings().all()]


def _rows_today(upcoming_only: bool):
    """
    Today’s sessions (local date).
    If upcoming_only=True, include start_times >= now_local::time.
    Includes aggregated names.
    """
    time_filter = "AND s.start_time >= (now_local.ts)::time" if upcoming_only else ""
    sql = text(f"""
        WITH now_local AS (
            SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
        )
        SELECT
            s.id,
            s.session_date,
            s.start_time,
            s.capacity,
            s.booked_count,
            s.status,
            COALESCE(s.notes, '') AS notes,
            COALESCE((
                SELECT STRING_AGG(nm, ', ' ORDER BY nm)
                FROM (
                    SELECT DISTINCT COALESCE(c2.name, '') AS nm
                    FROM bookings b2
                    JOIN clients  c2 ON c2.id = b2.client_id
                    WHERE b2.session_id = s.id
                      AND b2.status = 'confirmed'
                ) d
            ), '') AS names
        FROM sessions s
        CROSS JOIN now_local
        WHERE s.session_date = (now_local.ts)::date
        {time_filter}
        ORDER BY s.session_date, s.start_time;
    """)
    with get_session() as s:
        return [dict(r) for r in s.execute(sql, {"tz": TZ_NAME}).mappings().all()]


# ──────────────────────────────────────────────────────────────────────────────
# Formatting
# ──────────────────────────────────────────────────────────────────────────────

def _fmt_status(row: dict) -> str:
    full = (str(row["status"]).lower() == "full") or (row["booked_count"] >= row["capacity"])
    return "🔒 full" if full else "✅ open"

def _fmt_rows_with_names(rows: list[dict]) -> str:
    if not rows:
        return "— none —"
    lines = []
    for r in rows:
        hhmm   = str(r["start_time"])[:5]
        names  = (r.get("names") or "").strip()
        status = _fmt_status(r)
        who = "(no bookings)" if not names else names
        lines.append(f"• {hhmm} – {who}  ({status})")
    return "\n".join(lines)

def _fmt_today_block(upcoming_only: bool) -> str:
    rows = _rows_today(upcoming_only=upcoming_only)
    header = "🗓 Today’s sessions (upcoming)" if upcoming_only else "🗓 Today’s sessions (full day)"
    return f"{header}\n{_fmt_rows_with_names(rows)}"


# ──────────────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────────────

def register_tasks(app):
    @app.post("/tasks/admin-notify")
    def admin_notify():
        """
        Hourly admin summary:
          • 04:00 UTC pass (≈ 06:00 SAST): full-day overview
          • Other hours: upcoming-only
          • Always append a 'next hour' preview (even if none)
        """
        try:
            src = request.args.get("src", "unknown")
            logging.info(f"[admin-notify] src={src}")

            # Align hour check to DB clock
            with get_session() as s:
                now_utc_hour = s.execute(text("SELECT EXTRACT(HOUR FROM now())::int AS h")).mappings().first()["h"]

            body_today = _fmt_today_block(upcoming_only=False if now_utc_hour == 4 else True)

            nxt = _rows_next_hour()
            nxt_text = "🕒 Next hour:\n" + _fmt_rows_with_names(nxt) if nxt else "🕒 Next hour: no upcoming session."

            msg = f"{body_today}\n\n{nxt_text}"

            to = normalize_wa(NADINE_WA)
            if not to:
                logging.warning("[admin-notify] NADINE_WA not configured.")
                return "ok", 200

            send_whatsapp_text(to, msg)
            logging.info("[TASKS] admin-notify sent")
            return "ok", 200

        except Exception:
            logging.exception("admin-notify failed")
            return "error", 500

    @app.post("/tasks/run-reminders")
    def run_reminders():
        """
        Client reminder runner:
          • daily=0 (default) → next-hour reminders to booked clients
          • daily=1 → send admin a daily recap (manual check)
        """
        try:
            src = request.args.get("src", "unknown")
            daily = request.args.get("daily", "0") == "1"
            logging.info(f"[run-reminders] src={src}")

            if daily:
                rows = _rows_today(upcoming_only=False)
                to = normalize_wa(NADINE_WA)
                if to:
                    send_whatsapp_text(to, f"🗓 Today (full day)\n{_fmt_rows_with_names(rows)}")
                logging.info(f"[TASKS] run-reminders sent=0 [src={src}]")
                return "ok sent=0", 200

            # Next-hour client reminders
            rows = _rows_next_hour()
            sent = 0
            if not rows:
                logging.info(f"[TASKS] run-reminders sent={sent} [src={src}]")
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
                        send_whatsapp_text(
                            normalize_wa(a["wa"]),
                            f"⏰ Reminder: Your Pilates session starts at {hhmm} today. Reply CANCEL if you cannot attend."
                        )
                        sent += 1

            logging.info(f"[TASKS] run-reminders sent={sent} [src={src}]")
            return f"ok sent={sent}", 200

        except Exception:
            logging.exception("run-reminders failed")
            return "error", 500
