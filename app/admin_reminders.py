# app/admin_reminders.py
from __future__ import annotations
import logging
from sqlalchemy import text
from flask import request
from .db import get_session
from .utils import normalize_wa, send_whatsapp_text
from .config import TZ_NAME, ADMIN_NUMBERS
from . import crud

# ─────────────────────────────────────────────
# SQL + formatting helpers
# ─────────────────────────────────────────────

def _rows_today(upcoming_only: bool) -> list[dict]:
    sql = f"""
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
                    WHERE b2.session_id = p.id
                      AND b2.status = 'confirmed'
                ) d
            ), '') AS names
        FROM pool p
        ORDER BY p.session_date, p.start_time
    """
    with get_session() as s:
        return [dict(r) for r in s.execute(text(sql), {"tz": TZ_NAME}).mappings().all()]

def _rows_upcoming_hours() -> str:
    sql = """
        WITH now_local AS (
            SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
        ),
        bounds AS (
            SELECT generate_series(
                date_trunc('hour', ts) + interval '1 hour',
                date_trunc('day', ts) + interval '18 hour',
                interval '1 hour'
            ) AS h
            FROM now_local
        )
        SELECT
            b.h AS block_start,
            b.h + interval '1 hour' AS block_end,
            s.id, s.session_date, s.start_time, s.capacity,
            s.booked_count, s.status, COALESCE(s.notes,'') AS notes,
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
        FROM bounds b
        LEFT JOIN sessions s
          ON (s.session_date + s.start_time) >= b.h
         AND (s.session_date + s.start_time) <  b.h + interval '1 hour'
         AND s.session_date = (b.h)::date
        ORDER BY b.h, s.start_time
    """
    with get_session() as s:
        rows = [dict(r) for r in s.execute(text(sql), {"tz": TZ_NAME}).mappings().all()]

    out = ["🕒 Upcoming hours:"]
    seen_blocks = []
    for r in rows:
        bs = r["block_start"].strftime("%H:%M")
        if bs in seen_blocks:
            continue
        seen_blocks.append(bs)
        block_sessions = [x for x in rows if x["block_start"] == r["block_start"]]
        out.append(f"{bs}–{r['block_end'].strftime('%H:%M')}")
        if not any(x["id"] for x in block_sessions):
            out.append("— none —")
        else:
            for sess in block_sessions:
                if sess["id"] is None:
                    continue
                full = (str(sess["status"]).lower() == "full") or (sess["booked_count"] >= sess["capacity"])
                status = "🔒 full" if full else "✅ open"
                names = (sess.get("names") or "").strip()
                names_part = " (no bookings)" if not names else f" — {names}"
                out.append(f"• {str(sess['start_time'])[:5]}{names_part}  ({status})")
    return "\n".join(out)

def _fmt_rows(rows: list[dict]) -> str:
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

# ─────────────────────────────────────────────
# Core admin senders
# ─────────────────────────────────────────────

def _send_to_admins(body: str) -> None:
    for admin in ADMIN_NUMBERS:
        send_whatsapp_text(normalize_wa(admin), body)

def run_admin_tick(force_hour: int | None = None) -> None:
    with get_session() as s:
        if force_hour is not None:
            now_utc_hour = force_hour
        else:
            now_utc_hour = s.execute(
                text("SELECT EXTRACT(HOUR FROM now())::int AS h")
            ).mappings().first()["h"]

    full_day = (now_utc_hour == 4)  # 04:00 UTC ≈ 06:00 SAST
    today = _rows_today(upcoming_only=not full_day)
    header = "🗓 Today’s sessions (full day)" if full_day else "🗓 Today’s sessions (upcoming)"
    body_today = header + "\n" + _fmt_rows(today)
    hours_block = _rows_upcoming_hours()
    msg = f"{body_today}\n\n{hours_block}"
    _send_to_admins(msg)

    # Inbox entry only — no duplicate WhatsApp send
    crud.inbox_upsert(
        kind="hourly",
        title="Hourly update",
        body=msg,
        source="cron",
        status="open",
        is_unread=True,
        action_required=False,
        digest=f"hourly-{msg[:20]}",
    )
    logging.info("[ADMIN] tick sent + inbox")

def run_daily_recap() -> None:
    today = _rows_today(upcoming_only=False)
    body = "🗓 Today’s sessions (full day)\n" + _fmt_rows(today)

    # Send once via WhatsApp
    _send_to_admins(body)

    # Store inbox silently
    crud.inbox_upsert(
        kind="recap",
        title="20:00 recap",
        body=body,
        source="cron",
        status="open",
        is_unread=True,
        action_required=False,
        digest=f"recap-{body[:20]}",
    )
    logging.info("[ADMIN] daily recap sent + inbox")

# ─────────────────────────────────────────────
# Flask wiring
# ─────────────────────────────────────────────

def register_admin_reminders(app):
    @app.post("/tasks/admin-notify")
    def admin_notify():
        try:
            src = request.args.get("src", "unknown")
            force_hour = request.args.get("hour")
            logging.info(f"[admin-notify] src={src} force_hour={force_hour}")
            run_admin_tick(int(force_hour) if force_hour else None)
            return "ok", 200
        except Exception:
            logging.exception("admin-notify failed")
            return "error", 500

    @app.post("/tasks/admin-recap")
    def admin_recap():
        try:
            src = request.args.get("src", "unknown")
            logging.info(f"[admin-recap] src={src}")
            run_daily_recap()
            return "ok recap", 200
        except Exception:
            logging.exception("admin-recap failed")
            return "error", 500
