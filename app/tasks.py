    # app/tasks.py
from __future__ import annotations

import logging
from flask import request
from sqlalchemy import text

from .db import get_session
from .utils import normalize_wa, send_whatsapp_text  # keep it simple & reliable
from .config import ADMIN_NUMBERS, TZ_NAME


# ───────────────────────────
# Session lookups (SA local)
# ───────────────────────────

def _sessions_next_hour() -> list[dict]:
    """
    Sessions that start within the next hour in local time (TZ_NAME).
    Note: avoid using CTE name 'window' (keyword) → use 'win' instead.
    """
    with get_session() as s:
        rows = s.execute(
            text("""
                WITH now_local AS (
                    SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
                ),
                win AS (
                    SELECT ts, (ts + INTERVAL '1 hour') AS ts_plus FROM now_local
                )
                SELECT id, session_date, start_time, capacity, booked_count,
                       status, COALESCE(notes,'') AS notes
                FROM sessions, win
                WHERE (session_date + start_time) >= win.ts
                  AND (session_date + start_time) <  win.ts_plus
                ORDER BY start_time
            """),
            {"tz": TZ_NAME},
        ).mappings().all()
        return [dict(r) for r in rows]


def _sessions_today_upcoming(include_names: bool = False) -> list[dict]:
    """
    Today’s sessions that are still upcoming (local date/time).
    If include_names=True, returns aggregated attendee names in 'names' field.
    """
    if not include_names:
        with get_session() as s:
            rows = s.execute(
                text("""
                    WITH now_local AS (
                        SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
                    )
                    SELECT id, session_date, start_time, capacity, booked_count,
                           status, COALESCE(notes,'') AS notes
                    FROM sessions, now_local
                    WHERE session_date = (now_local.ts)::date
                      AND start_time >= (now_local.ts)::time
                    ORDER BY session_date, start_time
                """),
                {"tz": TZ_NAME},
            ).mappings().all()
            return [dict(r) for r in rows]

    # include_names=True → aggregate attendee names
    with get_session() as s:
        rows = s.execute(
            text("""
                WITH now_local AS (
                    SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
                ),
                upcoming AS (
                    SELECT s.id, s.session_date, s.start_time, s.capacity,
                           s.booked_count, s.status, COALESCE(s.notes,'') AS notes
                    FROM sessions s, now_local
                    WHERE s.session_date = (now_local.ts)::date
                      AND s.start_time  >= (now_local.ts)::time
                )
                SELECT u.*,
                       COALESCE(
                           NULLIF(
                               STRING_AGG(DISTINCT COALESCE(c.name,''), ', ' ORDER BY c.name),
                               ''
                           ), '—'
                       ) AS names
                FROM upcoming u
                LEFT JOIN bookings b ON b.session_id = u.id AND b.status = 'confirmed'
                LEFT JOIN clients  c ON c.id = b.client_id
                GROUP BY u.id, u.session_date, u.start_time, u.capacity,
                         u.booked_count, u.status, u.notes
                ORDER BY u.session_date, u.start_time
            """),
            {"tz": TZ_NAME},
        ).mappings().all()
        return [dict(r) for r in rows]


def _sessions_today_full_day(include_names: bool = False) -> list[dict]:
    """
    All of today’s sessions (local date). Optionally aggregate attendee names.
    """
    if not include_names:
        with get_session() as s:
            rows = s.execute(
                text("""
                    WITH now_local AS (
                        SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
                    )
                    SELECT id, session_date, start_time, capacity, booked_count,
                           status, COALESCE(notes,'') AS notes
                    FROM sessions, now_local
                    WHERE session_date = (now_local.ts)::date
                    ORDER BY session_date, start_time
                """),
                {"tz": TZ_NAME},
            ).mappings().all()
            return [dict(r) for r in rows]

    # include_names=True → aggregate attendee names
    with get_session() as s:
        rows = s.execute(
            text("""
                WITH now_local AS (
                    SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
                ),
                today AS (
                    SELECT s.id, s.session_date, s.start_time, s.capacity,
                           s.booked_count, s.status, COALESCE(s.notes,'') AS notes
                    FROM sessions s, now_local
                    WHERE s.session_date = (now_local.ts)::date
                )
                SELECT t.*,
                       COALESCE(
                           NULLIF(
                               STRING_AGG(DISTINCT COALESCE(c.name,''), ', ' ORDER BY c.name),
                               ''
                           ), '—'
                       ) AS names
                FROM today t
                LEFT JOIN bookings b ON b.session_id = t.id AND b.status = 'confirmed'
                LEFT JOIN clients  c ON c.id = b.client_id
                GROUP BY t.id, t.session_date, t.start_time, t.capacity,
                         t.booked_count, t.status, t.notes
                ORDER BY t.session_date, t.start_time
            """),
            {"tz": TZ_NAME},
        ).mappings().all()
        return [dict(r) for r in rows]


def _sessions_tomorrow_full_day(include_names: bool = False) -> list[dict]:
    """
    All of tomorrow’s sessions (local date). Optionally aggregate attendee names.
    """
    if not include_names:
        with get_session() as s:
            rows = s.execute(
                text("""
                    WITH now_local AS (
                        SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
                    )
                    SELECT id, session_date, start_time, capacity, booked_count,
                           status, COALESCE(notes,'') AS notes
                    FROM sessions, now_local
                    WHERE session_date = ((now_local.ts)::date + INTERVAL '1 day')::date
                    ORDER BY session_date, start_time
                """),
                {"tz": TZ_NAME},
            ).mappings().all()
            return [dict(r) for r in rows]

    with get_session() as s:
        rows = s.execute(
            text("""
                WITH now_local AS (
                    SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
                ),
                tomorrow AS (
                    SELECT s.id, s.session_date, s.start_time, s.capacity,
                           s.booked_count, s.status, COALESCE(s.notes,'') AS notes
                    FROM sessions s, now_local
                    WHERE s.session_date = ((now_local.ts)::date + INTERVAL '1 day')::date
                )
                SELECT t.*,
                       COALESCE(
                           NULLIF(
                               STRING_AGG(DISTINCT COALESCE(c.name,''), ', ' ORDER BY c.name),
                               ''
                           ), '—'
                       ) AS names
                FROM tomorrow t
                LEFT JOIN bookings b ON b.session_id = t.id AND b.status = 'confirmed'
                LEFT JOIN clients  c ON c.id = b.client_id
                GROUP BY t.id, t.session_date, t.start_time, t.capacity,
                         t.booked_count, t.status, t.notes
                ORDER BY t.session_date, t.start_time
            """),
            {"tz": TZ_NAME},
        ).mappings().all()
        return [dict(r) for r in rows]


# ───────────────────────────
# Formatting helpers
# ───────────────────────────

def _fmt_rows(rows: list[dict], include_names: bool = True) -> str:
    """
    Build WhatsApp-friendly lines with names shown (as requested).
    Example:
      • 08:00 — Alice, Ben, C.Dlamini
    If no attendees: show "— none booked —".
    """
    if not rows:
        return "— none —"

    out: list[str] = []
    for r in rows:
        names = (r.get("names") or "").strip()
        names_txt = names if names and names != "—" else "— none booked —"
        hhmm = str(r["start_time"])[:5]
        out.append(f"• {hhmm} — {names_txt}")
    return "\n".join(out)


def _fmt_today_block(upcoming_only: bool, include_names: bool = True) -> str:
    items = (
        _sessions_today_upcoming(include_names=include_names)
        if upcoming_only
        else _sessions_today_full_day(include_names=include_names)
    )
    header = (
        f"🗓 Today’s sessions (upcoming: {len(items)})"
        if upcoming_only else
        "🗓 Today’s sessions (full day)"
    )
    return f"{header}\n{_fmt_rows(items, include_names=include_names)}"


# ───────────────────────────
# Routes
# ───────────────────────────

def register_tasks(app):
    @app.post("/tasks/admin-notify")
    def admin_notify():
        """
        Hourly admin summary.
        • At ~04:00 UTC (≈ 06:00 SAST) first pass: show full-day view with names.
        • Other hours: upcoming-only with names.
        • Always append a “next hour” line (even if none).
        """
        try:
            src = request.args.get("src", "unknown")
            logging.info(f"[admin-notify] src={src}")

            # Use DB now() just to get UTC hour; localization is done in SQL above.
            with get_session() as s:
                now_utc_hour = s.execute(
                    text("SELECT EXTRACT(HOUR FROM now())::int AS h")
                ).mappings().first()["h"]

            body_today = _fmt_today_block(
                upcoming_only=False if now_utc_hour == 4 else True,
                include_names=True,
            )

            # Build "next hour" with names
            nh_sessions = _sessions_next_hour()
            if nh_sessions:
                # fetch names for those session ids
                ids = [r["id"] for r in nh_sessions]
                names_map = _attendee_names_map(ids)
                # attach names & format
                enriched = []
                for r in nh_sessions:
                    r = dict(r)
                    r["names"] = names_map.get(r["id"], "— none booked —")
                    enriched.append(r)
                nh_text = "🕒 Next hour:\n" + _fmt_rows(enriched, include_names=True)
            else:
                nh_text = "🕒 Next hour: no upcoming session."

            msg = f"{body_today}\n\n{nh_text}"

            # Send to all configured admin numbers
            sent_any = False
            for raw in ADMIN_NUMBERS:
                to = normalize_wa(raw)
                if not to:
                    continue
                send_whatsapp_text(to, msg)
                sent_any = True

            if not sent_any:
                logging.warning("[admin-notify] No ADMIN_NUMBERS configured.")

            logging.info("[TASKS] admin-notify sent")
            return "ok", 200

        except Exception:
            logging.exception("admin-notify failed")
            return "error", 500

    @app.post("/tasks/run-reminders")
    def run_reminders():
        """
        • daily=0 (default): client next-hour reminders (only if attendees exist).
        • daily=1: admin recap for today (kept for manual tests / fallback).
        """
        try:
            src = request.args.get("src", "unknown")
            daily = request.args.get("daily", "0") == "1"
            logging.info(f"[run-reminders] src={src}")

            if daily:
                today_all = _sessions_today_full_day(include_names=True)
                header = f"🗓 Today’s sessions (count: {len(today_all)})"
                body = _fmt_rows(today_all, include_names=True)
                sent_any = False
                for raw in ADMIN_NUMBERS:
                    to = normalize_wa(raw)
                    if not to:
                        continue
                    send_whatsapp_text(to, f"{header}\n{body}")
                    sent_any = True
                if not sent_any:
                    logging.warning("[run-reminders daily] No ADMIN_NUMBERS configured.")
                logging.info(f"[TASKS] run-reminders sent=0 [src={src}]")
                return "ok sent=0", 200

            # Hourly client reminders (next hour)
            rows = _sessions_next_hour()
            sent = 0
            if not rows:
                logging.info(f"[TASKS] run-reminders sent={sent} [src={src}]")
                return f"ok sent={sent}", 200

            # Fetch attendees per session and send plain text reminders
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
                        num = normalize_wa(a["wa"])
                        if not num:
                            continue
                        send_whatsapp_text(
                            num,
                            f"⏰ Reminder: Your Pilates session starts at {hhmm} today. Reply CANCEL if you cannot attend."
                        )
                        sent += 1

            logging.info(f"[TASKS] run-reminders sent={sent} [src={src}]")
            return f"ok sent={sent}", 200

        except Exception:
            logging.exception("run-reminders failed")
            return "error", 500

    @app.post("/tasks/debug-ping-admin")
    def debug_ping_admin():
        try:
            sent_any = False
            for raw in ADMIN_NUMBERS:
                to = normalize_wa(raw)
                if not to:
                    continue
                send_whatsapp_text(to, "Ping from /tasks/debug-ping-admin ✅")
                sent_any = True
            if not sent_any:
                return "no admin numbers configured", 200
            return "sent", 200
        except Exception:
            logging.exception("debug-ping-admin failed")
            return "error", 500


# ───────────────────────────
# Small helper to get names for a set of session IDs
# ───────────────────────────

def _attendee_names_map(session_ids: list[int]) -> dict[int, str]:
    """
    Returns {session_id: "Alice, Ben, …"} for confirmed bookings.
    """
    if not session_ids:
        return {}
    with get_session() as s:
        rows = s.execute(
            text("""
                SELECT b.session_id,
                       COALESCE(
                           NULLIF(
                               STRING_AGG(DISTINCT COALESCE(c.name,''), ', ' ORDER BY c.name),
                               ''
                           ), '— none booked —'
                       ) AS names
                FROM bookings b
                JOIN clients  c ON c.id = b.client_id
                WHERE b.status = 'confirmed' AND b.session_id = ANY(:ids)
                GROUP BY b.session_id
            """),
            {"ids": session_ids},
        ).mappings().all()
        return {r["session_id"]: (r["names"] or "— none booked —") for r in rows}
