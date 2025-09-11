# app/reminders.py
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from sqlalchemy import text

from .db import get_session
from .utils import normalize_wa, send_whatsapp_text
from .config import TZ_NAME, ADMIN_NUMBERS, NADINE_WA
from . import crud
from .message_templates import (
    fmt_rows_with_names,
    admin_today_block,
    admin_next_hour_block,
    admin_future_look_block,
    client_h1_text,
    client_d1_text,
)

# ──────────────────────────────────────────────────────────────────────────────
# Data helpers
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class SessionRow:
    id: int
    session_date: str   # ISO date from DB (YYYY-MM-DD)
    start_time: str     # HH:MM:SS
    capacity: int
    booked_count: int
    status: str
    notes: str
    names: str

def _rows_today(upcoming_only: bool) -> List[SessionRow]:
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
        rows = s.execute(text(sql), {"tz": TZ_NAME}).mappings().all()
        return [SessionRow(**dict(r)) for r in rows]

def _rows_next_hour() -> List[SessionRow]:
    sql = """
        WITH now_local AS (
            SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
        ),
        bounds AS (
            SELECT date_trunc('hour', ts) AS h,
                   date_trunc('hour', ts) + INTERVAL '1 hour' AS h_plus
            FROM now_local
        )
        SELECT
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
        FROM sessions s, bounds
        WHERE (s.session_date + s.start_time) >= bounds.h
          AND (s.session_date + s.start_time) <  bounds.h_plus
        ORDER BY s.start_time
    """
    with get_session() as s:
        rows = s.execute(text(sql), {"tz": TZ_NAME}).mappings().all()
        return [SessionRow(**dict(r)) for r in rows]

def _rows_tomorrow() -> List[SessionRow]:
    sql = """
        WITH now_local AS (
            SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
        )
        SELECT
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
        FROM sessions s, now_local
        WHERE s.session_date = ((now_local.ts)::date + INTERVAL '1 day')::date
        ORDER BY s.session_date, s.start_time
    """
    with get_session() as s:
        rows = s.execute(text(sql), {"tz": TZ_NAME}).mappings().all()
        return [SessionRow(**dict(r)) for r in rows]

# ──────────────────────────────────────────────────────────────────────────────
# Idempotent send-log
# ──────────────────────────────────────────────────────────────────────────────

def _sendlog_exists(session_id: int, wa: str, kind: str) -> bool:
    sql = """
        SELECT 1
        FROM reminders_sendlog
        WHERE session_id = :sid AND wa = :wa AND kind = :kind
        LIMIT 1
    """
    with get_session() as s:
        row = s.execute(text(sql), {"sid": session_id, "wa": wa, "kind": kind}).first()
        return bool(row)

def _sendlog_insert(session_id: int, wa: str, kind: str) -> None:
    sql = """
        INSERT INTO reminders_sendlog (session_id, wa, kind, fired_at)
        VALUES (:sid, :wa, :kind, now())
        ON CONFLICT (session_id, wa, kind) DO NOTHING
    """
    with get_session() as s:
        s.execute(text(sql), {"sid": session_id, "wa": wa, "kind": kind})

# ──────────────────────────────────────────────────────────────────────────────
# Client reminder ticks
# ──────────────────────────────────────────────────────────────────────────────

def _attendees_for_session(session_id: int) -> List[str]:
    sql = """
        SELECT c.wa_number AS wa
        FROM bookings b
        JOIN clients  c ON c.id = b.client_id
        WHERE b.session_id = :sid AND b.status = 'confirmed'
    """
    with get_session() as s:
        rows = s.execute(text(sql), {"sid": session_id}).mappings().all()
        return [normalize_wa(r["wa"]) for r in rows if r.get("wa")]

def _rows_in_window(minutes_from: int, minutes_to: int) -> List[SessionRow]:
    """
    Return sessions starting between [now+minutes_from, now+minutes_to) in local TZ.
    Useful for 60-minute and 1440-minute windows.
    """
    sql = """
        WITH now_local AS (
            SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
        ),
        bounds AS (
            SELECT (ts + make_interval(mins => :from_m)) AS a,
                   (ts + make_interval(mins => :to_m))   AS b
            FROM now_local
        )
        SELECT
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
        FROM sessions s, bounds
        WHERE (s.session_date + s.start_time) >= bounds.a
          AND (s.session_date + s.start_time) <  bounds.b
        ORDER BY s.start_time
    """
    with get_session() as s:
        rows = s.execute(
            text(sql), {"tz": TZ_NAME, "from_m": minutes_from, "to_m": minutes_to}
        ).mappings().all()
        return [SessionRow(**dict(r)) for r in rows]

def run_client_tick() -> int:
    """
    Sends client reminders:
      • D-1 (24 hours before): window [1440, 1500) to be tolerant of cron drift.
      • H-1 (1 hour before):  window [60, 90).
    Removes any 'CANCEL' instruction from copy (per spec).
    Returns number of messages sent.
    """
    sent = 0

    # D-1 window (24h ± tolerance)
    for sess in _rows_in_window(1440, 1500):
        hhmm = sess.start_time[:5]
        attendees = _attendees_for_session(sess.id)
        for wa in attendees:
            if not wa:
                continue
            if _sendlog_exists(sess.id, wa, "D-1"):
                continue
            msg = client_d1_text(hhmm)
            send_whatsapp_text(wa, msg)
            _sendlog_insert(sess.id, wa, "D-1")
            sent += 1

    # H-1 window (1h ± tolerance)
    for sess in _rows_in_window(60, 90):
        hhmm = sess.start_time[:5]
        attendees = _attendees_for_session(sess.id)
        for wa in attendees:
            if not wa:
                continue
            if _sendlog_exists(sess.id, wa, "H-1"):
                continue
            msg = client_h1_text(hhmm)
            send_whatsapp_text(wa, msg)
            _sendlog_insert(sess.id, wa, "H-1")
            sent += 1

    logging.info("[REMINDERS] client_tick sent=%s", sent)
    return sent

# ──────────────────────────────────────────────────────────────────────────────
# Admin summaries
# ──────────────────────────────────────────────────────────────────────────────

def _send_to_admins(body: str) -> None:
    targets = ADMIN_NUMBERS or ([NADINE_WA] if NADINE_WA else [])
    for admin in targets:
        if not admin:
            continue
        send_whatsapp_text(normalize_wa(admin), body)

def run_admin_tick() -> None:
    """
    Hourly admin summary (06:00–19:00 SAST via Cron hitting /tasks/admin-notify):
      • 06:00 SAST → FULL DAY (morning prep)
      • Other hours within the band → UPCOMING
      • Always appends “Next hour”
      • Writes idempotent admin_inbox entry using digest YYYY-MM-DD-HH|admin-tick
    """
    with get_session() as s:
        now_utc_hour = s.execute(
            text("SELECT EXTRACT(HOUR FROM now())::int AS h")
        ).mappings().first()["h"]
        bucket = s.execute(
            text("SELECT to_char((now() AT TIME ZONE :tz), 'YYYY-MM-DD-HH') AS b"),
            {"tz": TZ_NAME},
        ).mappings().first()["b"]

    # 06:00 SAST ≈ 04:00 UTC
    full_day = (now_utc_hour == 4)

    today_block = admin_today_block(_rows_today(upcoming_only=not full_day))
    next_hour_rows = _rows_next_hour()
    msg = today_block + "\n\n" + admin_next_hour_block(next_hour_rows)

    # Dedup inbox by digest
    digest = f"{bucket}|admin-tick"
    digest_hex = hashlib.sha256(digest.encode("utf-8")).hexdigest()

    _send_to_admins(msg)
    crud.inbox_upsert(
        kind="hourly",
        title="Hourly update",
        body=msg,
        source="cron",
        status="open",
        is_unread=True,
        action_required=False,
        digest=digest_hex,
    )
    logging.info("[REMINDERS] admin_tick sent + inbox digest=%s", digest_hex)

def run_admin_daily() -> None:
    """
    20:00 SAST job (Cron calls /tasks/run-reminders?daily=1):
      • Send full-day recap (today) to admins.
      • Send a “future look” for tomorrow.
      • Write idempotent inbox entry with digest YYYY-MM-DD|recap.
    """
    today_rows = _rows_today(upcoming_only=False)
    recap = admin_today_block(today_rows, label="🗓 Today’s sessions (full day)")
    future = admin_future_look_block(_rows_tomorrow())
    msg = f"{recap}\n\n{future}"

    with get_session() as s:
        bucket = s.execute(
            text("SELECT to_char((now() AT TIME ZONE :tz), 'YYYY-MM-DD') AS b"),
            {"tz": TZ_NAME},
        ).mappings().first()["b"]

    digest = f"{bucket}|recap"
    digest_hex = hashlib.sha256(digest.encode("utf-8")).hexdigest()

    _send_to_admins(msg)
    crud.inbox_upsert(
        kind="recap",
        title="20:00 recap + tomorrow",
        body=msg,
        source="cron",
        status="open",
        is_unread=True,
        action_required=False,
        digest=digest_hex,
    )
    logging.info("[REMINDERS] admin_daily recap sent + inbox digest=%s", digest_hex)
