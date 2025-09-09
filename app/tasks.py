# app/tasks.py
from __future__ import annotations
import logging
from sqlalchemy import text
from flask import request
from .db import get_session
from .utils import normalize_wa, send_whatsapp_text
from .config import NADINE_WA, TZ_NAME
from . import crud

# ─────────────────────────────────────────────────────────────────────────────
# Row builders with names included (no WINDOW keyword conflicts).
# ─────────────────────────────────────────────────────────────────────────────

def _rows_today(upcoming_only: bool, include_names: bool = True):
    """
    Return today's sessions (optionally upcoming only), with aggregated client names.
    """
    base = f"""
        WITH now_local AS (
            SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
        ),
        pool AS (
            SELECT s.id, s.session_date, s.start_time, s.capacity,
                   s.booked_count, s.status, COALESCE(s.notes,'') AS notes
            FROM sessions s, now_local
            WHERE s.session_date = (now_local.ts)::date
            {"AND s.start_time >= (now_local.ts)::time" if upcoming_only else ""}
        )
        SELECT
            p.*,
            COALESCE((
                SELECT STRING_AGG(nm, ', ' ORDER BY nm)
                FROM (
                    SELECT DISTINCT COALESCE(c2.name, '') AS nm
                    FROM bookings b2
                    JOIN clients  c2 ON c2.id = b2.client_id
                    WHERE b2.session_id = p.id AND b2.status = 'confirmed'
                ) d
            ), '') AS names
        FROM pool p
        ORDER BY p.session_date, p.start_time
    """
    with get_session() as s:
        return [dict(r) for r in s.execute(text(base), {"tz": TZ_NAME}).mappings().all()]

def _rows_next_hour():
    """
    Sessions starting within the next hour (local TZ), with names.
    """
    sql = """
        WITH now_local AS (
            SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
        ),
        bounds AS (
            SELECT date_trunc('hour', ts) AS h, date_trunc('hour', ts) + INTERVAL '1 hour' AS h_plus
            FROM now_local
        )
        SELECT
            s.id, s.session_date, s.start_time, s.capacity, s.booked_count, s.status, COALESCE(s.notes,'') AS notes,
            COALESCE((
                SELECT STRING_AGG(nm, ', ' ORDER BY nm)
                FROM (
                    SELECT DISTINCT COALESCE(c2.name, '') AS nm
                    FROM bookings b2
                    JOIN clients  c2 ON c2.id = b2.client_id
                    WHERE b2.session_id = s.id AND b2.status = 'confirmed'
                ) d
            ), '') AS names
        FROM sessions s, bounds
        WHERE (s.session_date + s.start_time) >= bounds.h
          AND (s.session_date + s.start_time) <  bounds.h_plus
        ORDER BY s.start_time
    """
    with get_session() as s:
        return [dict(r) for r in s.execute(text(sql), {"tz": TZ_NAME}).mappings().all()]

# ─────────────────────────────────────────────────────────────────────────────
# Formatting
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_rows_with_names(rows):
    if not rows:
        return "— none —"
    out = []
    for r in rows:
        full = (str(r["status"]).lower() == "full") or (r["booked_count"] >= r["capacity"])
        status = "🔒 full" if full else "✅ open"
        names = (r.get("names") or "").strip()
        names_part = " (no bookings)" if not names else f" — {names}"
        out.append(f"• {str(r['start_time'])[:5]}{names_part}  ({status})")
    return "\n".join(out)

def _fmt_today_block(upcoming_only: bool, include_names: bool = True):
    items = _rows_today(upcoming_only=upcoming_only, include_names=include_names)
    header = "🗓 Today’s sessions (upcoming)" if upcoming_only else "🗓 Today’s sessions (full day)"
    return f"{header}\n{_fmt_rows_with_names(items)}"

# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

def register_tasks(app):
    @app.post("/tasks/admin-notify")
    def admin_notify():
        """
        Hourly admin summary (06:00–18:00 SAST via CRON).
        • 04:00 UTC pass (≈06:00 SAST) sends FULL DAY; other hours send UPCOMING.
        • Always appends “Next hour”.
        • Inserts (idempotently) an 'hourly' inbox row bucketed by hour.
        """
        try:
            src = request.args.get("src", "unknown")
            logging.info(f"[admin-notify] src={src}")

            with get_session() as s:
                now_utc_hour = s.execute(text("SELECT EXTRACT(HOUR FROM now())::int AS h")).mappings().first()["h"]
                # bucket like '2025-09-07-13'
                bucket = s.execute(
                    text("SELECT to_char((now() AT TIME ZONE :tz), 'YYYY-MM-DD-HH') AS b"),
                    {"tz": TZ_NAME}
                ).mappings().first()["b"]

            body_today = _fmt_today_block(upcoming_only=False if now_utc_hour == 4 else True, include_names=True)
            nxt = _rows_next_hour()
            nh_text = "🕒 Next hour:\n" + _fmt_rows_with_names(nxt) if nxt else "🕒 Next hour: no upcoming session."
            msg = f"{body_today}\n\n{nh_text}"

            # Send to admin (if configured)
            to = normalize_wa(NADINE_WA)
            if to:
                send_whatsapp_text(to, msg)

            # Inbox: idempotent hourly entry
            crud.inbox_upsert(
                kind="recap",              # ← not "daily"
                title="20:00 recap",
                body=body,
                source="cron",
                status="open",
                is_unread=True,
                action_required=False,
                bucket=bucket, 
            )
            logging.info("[TASKS] admin-notify sent + inbox")
            return "ok", 200

        except Exception:
            logging.exception("admin-notify failed")
            return "error", 500

    @app.post("/tasks/run-reminders")
    def run_reminders():
        """
        - daily=0 (default): client next-hour reminders (if any).
        - daily=1: admin 20:00 daily recap (today), also records a 'daily' inbox row bucketed by date.
        """
        try:
            src = request.args.get("src", "unknown")
            daily = request.args.get("daily", "0") == "1"
            logging.info(f"[run-reminders] src={src}")

            if daily:
                # Build today's full-day recap with names.
                today_all = _rows_today(upcoming_only=False, include_names=True)
                body = _fmt_rows_with_names(today_all)
                header = "🗓 Today’s sessions (full day)"
                msg = f"{header}\n{body}"

                to = normalize_wa(NADINE_WA)
                if to:
                    send_whatsapp_text(to, msg)

                # bucket by date 'YYYY-MM-DD'
                with get_session() as s:
                    bucket = s.execute(
                        text("SELECT to_char((now() AT TIME ZONE :tz), 'YYYY-MM-DD') AS b"),
                        {"tz": TZ_NAME}
                    ).mappings().first()["b"]

                crud.inbox_upsert(
                    kind="recap",
                    title="20:00 recap",
                    body=body,
                    source="cron",
                )
                logging.info("[TASKS] run-reminders daily recap + inbox")
                return "ok sent=0", 200

            # Hourly client reminders (unchanged here; you can keep templates if needed)
            rows = _rows_next_hour()
            sent = 0
            if not rows:
                logging.info(f"[TASKS] run-reminders sent={sent} [run-reminders] src={src}")
                return f"ok sent={sent}", 200

            with get_session() as s:
                for sess in rows:
                    attendees = s.execute(text("""
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
