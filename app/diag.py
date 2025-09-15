# app/diag.py
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, time
from typing import Dict, Any, List, Optional, Tuple

from flask import Blueprint, jsonify, request
from sqlalchemy import text

from .db import db_session
from .utils import LAST_RUN, ERROR_COUNTERS, send_template

diag_bp = Blueprint("diag", __name__)
log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Root
# ──────────────────────────────────────────────────────────────────────────────
@diag_bp.get("/")
def root_ok():
    return "ok", 200

# ──────────────────────────────────────────────────────────────────────────────
# DB health
# ──────────────────────────────────────────────────────────────────────────────
@diag_bp.get("/diag/db-test")
def db_test():
    try:
        with db_session() as s:
            s.execute(text("SELECT 1"))
        return jsonify({"ok": True, "result": 1}), 200
    except Exception:
        log.exception("db-test failed")
        return "error", 500

# ──────────────────────────────────────────────────────────────────────────────
# CRON / Observability snapshot
# ──────────────────────────────────────────────────────────────────────────────
@diag_bp.get("/diag/cron-status")
def cron_status():
    now_iso = datetime.utcnow().isoformat(timespec="seconds")
    return jsonify({
        "ok": True,
        "server_time": now_iso,
        "last_run": LAST_RUN,
        "error_counters": ERROR_COUNTERS,
    }), 200

# ──────────────────────────────────────────────────────────────────────────────
# Template smoke tests
# ──────────────────────────────────────────────────────────────────────────────
@diag_bp.post("/diag/test-client-template")
def test_client_template():
    to = request.args.get("to", "").strip()
    time_hhmm = request.args.get("time", "09:00").strip()
    ok, status, resp = send_template(
        to=to,
        template="session_tomorrow",
        lang="en",
        variables={"1": time_hhmm},
    )
    return jsonify({
        "ok": ok,
        "status_code": status,
        "response": resp,
        "to": to,
        "template": "session_tomorrow",
        "lang": "en",
    }), (200 if ok else 500)

@diag_bp.post("/diag/test-weekly-template")
def test_weekly_template():
    to = request.args.get("to", "").strip()
    name = request.args.get("name", "Client").strip()
    raw_items = request.args.get("items", "")
    if raw_items:
        parts = [p.strip() for p in raw_items.split(";") if p.strip()]
    else:
        parts = [v for k, v in sorted(request.args.items()) if k.startswith("item")]
    items_str = " \u2022 ".join(parts) if parts else "No sessions this week"
    ok, status, resp = send_template(
        to=to,
        template="weekly_template_message",
        lang="en",
        variables={"1": name, "2": items_str},
    )
    return jsonify({
        "ok": ok,
        "status_code": status,
        "response": resp,
        "to": to,
        "template": "weekly_template_message",
        "lang": "en",
        "vars": {"name": name, "items": items_str},
    }), (200 if ok else 500)

# ──────────────────────────────────────────────────────────────────────────────
# Weekly dry run (no send)
# ──────────────────────────────────────────────────────────────────────────────
@diag_bp.get("/diag/weekly-dry-run")
def weekly_dry_run():
    """
    Inspect which client sessions would be picked up by weekly reminders.
    Query:
      days=7 (default)
      status_in=confirmed (comma-separated)
      include_null_wa=0/1
    """
    days = int(request.args.get("days", "7"))
    status_in = request.args.get("status_in", "confirmed")
    include_null_wa = request.args.get("include_null_wa", "0") == "1"

    today = date.today()
    end = today + timedelta(days=days-1)
    statuses = [s.strip() for s in status_in.split(",") if s.strip()]

    with db_session() as s:
        q = """
        SELECT c.id AS client_id, c.name AS client_name, c.wa_number,
               sess.session_date, sess.start_time,
               b.status AS booking_status
        FROM bookings b
        JOIN clients c ON c.id = b.client_id
        JOIN sessions sess ON sess.id = b.session_id
        WHERE b.status = ANY(:statuses)
          AND sess.session_date BETWEEN :d0 AND :d1
          {wa_filter}
        ORDER BY sess.session_date, sess.start_time, c.name
        """.format(wa_filter="" if include_null_wa else "AND c.wa_number IS NOT NULL")
        rows = s.execute(text(q), {
            "statuses": statuses,
            "d0": today,
            "d1": end,
        }).mappings().all()

    payload = [dict(r) | {"would_send": True} for r in rows]
    with_wa = sum(1 for r in payload if r.get("wa_number"))
    without_wa = len(payload) - with_wa
    return jsonify({
        "ok": True,
        "window_days": days,
        "status_in": statuses,
        "include_null_wa": include_null_wa,
        "total_matches": len(payload),
        "with_wa_number": with_wa,
        "without_wa_number": without_wa,
        "sample_first_100": payload[:100],
    }), 200

# ──────────────────────────────────────────────────────────────────────────────
# Minimal seed (one client + two sessions)
# ──────────────────────────────────────────────────────────────────────────────
@diag_bp.post("/diag/seed-demo")
def seed_demo():
    wa = request.args.get("wa", "").strip()
    name = request.args.get("name", "Test").strip()
    t1 = request.args.get("t1", "09:00").strip()
    t2 = request.args.get("t2", "07:00").strip()

    d1 = date.today() + timedelta(days=1)
    d2 = date.today() + timedelta(days=2)

    with db_session() as s:
        cid = _ensure_client(s, name=name, wa=wa)
        sid1 = _ensure_session(s, d1, t1, capacity=6)
        sid2 = _ensure_session(s, d2, t2, capacity=6)
        _ensure_booking(s, cid, sid1, "confirmed")
        _ensure_booking(s, cid, sid2, "confirmed")
        _recalc_booked_counts(s, [sid1, sid2])

    return jsonify({
        "ok": True,
        "client": {"id": cid, "name": name, "wa_number": wa},
        "sessions_created": [{"id": sid1, "date": str(d1), "time": t1},
                             {"id": sid2, "date": str(d2), "time": t2}],
        "bookings": [{"session_id": sid1, "status": "confirmed"},
                     {"session_id": sid2, "status": "confirmed"}],
    }), 200

# ──────────────────────────────────────────────────────────────────────────────
# Rich seed for queries coverage (kept)
# ──────────────────────────────────────────────────────────────────────────────
@diag_bp.post("/diag/seed-queries")
def seed_queries():
    days = int(request.args.get("days", "7"))
    keep = request.args.get("keep", "0") == "1"
    guest_wa = request.args.get("guest", "27735534607").strip()

    today = date.today()
    end = today + timedelta(days=days - 1)
    times = ["07:00", "09:00", "17:30"]

    with db_session() as s:
        if not keep:
            _clear_window(s, today, end)

        cid_guest = _ensure_client(s, name="Test", wa=guest_wa)
        cid_fatima = _ensure_client(s, name="Fatima Khan", wa="27840000001")
        cid_bob = _ensure_client(s, name="Bob M.", wa="27840000002")
        cid_alice = _ensure_client(s, name="Alice N.", wa="27840000003")

        sess_ids: Dict[tuple, int] = {}
        d = today
        while d <= end:
            for hhmm in times:
                sid = _ensure_session(s, d, hhmm, capacity=6 if hhmm != "17:30" else 6)
                sess_ids[(d, hhmm)] = sid
            d += timedelta(days=1)

        sid_g1 = sess_ids[(today + timedelta(days=1), "09:00")]
        sid_g2 = sess_ids[(today + timedelta(days=2), "07:00")]
        _ensure_booking(s, cid_guest, sid_g1, "confirmed")
        _ensure_booking(s, cid_guest, sid_g2, "confirmed")

        sid_f1 = sess_ids[(today + timedelta(days=3), "09:00")]
        _ensure_booking(s, cid_fatima, sid_f1, "confirmed")

        sid_b1 = sess_ids[(today + timedelta(days=1), "09:00")]
        _ensure_booking(s, cid_bob, sid_b1, "cancelled")

        _recalc_booked_counts(s, list(sess_ids.values()))

        out = {
            "ok": True,
            "window": {"start": str(today), "end": str(end), "days": days},
            "clients": [
                {"id": cid_guest, "name": "Test", "wa_number": guest_wa},
                {"id": cid_fatima, "name": "Fatima Khan", "wa_number": "27840000001"},
                {"id": cid_bob, "name": "Bob M.", "wa_number": "27840000002"},
                {"id": cid_alice, "name": "Alice N.", "wa_number": "27840000003"},
            ],
            "sessions_created": len(sess_ids),
            "highlights": {
                "guest": [{"date": str(date.today() + timedelta(days=1)), "time": "09:00"},
                          {"date": str(date.today() + timedelta(days=2)), "time": "07:00"}],
                "fatima": [{"date": str(date.today() + timedelta(days=3)), "time": "09:00"}],
                "bob_cancelled": [{"date": str(date.today() + timedelta(days=1)), "time": "09:00"}],
                "alice": "no bookings",
            }
        }
        return jsonify(out), 200

# ──────────────────────────────────────────────────────────────────────────────
# NEW: Seed a Mon–Fri hourly grid with the requested pattern
# ──────────────────────────────────────────────────────────────────────────────
@diag_bp.post("/diag/seed-week-grid")
def seed_week_grid():
    """
    Seeds next workweek (Mon–Fri) with:
      06:00–09:00 → groups of 6 (capacity 6, 6 confirmed bookings)
      10:00–15:00 → alternating single/duo by hour (capacity 1 then 2)
      16:00–17:00 → groups of 6 (capacity 6)
    Params:
      keep=1           → do not clear existing sessions/bookings in the window (default clears)
      assign_wa=1      → assign fake MSISDNs to generated clients (default: wa NULL)
      start_monday=YYYY-MM-DD → override start Monday (optional)
    """
    keep = request.args.get("keep", "0") == "1"
    assign_wa = request.args.get("assign_wa", "0") == "1"
    start_override = request.args.get("start_monday", "").strip()

    start = _parse_date(start_override) if start_override else _next_monday(date.today())
    end = start + timedelta(days=4)  # Mon..Fri

    morning_hours = [6, 7, 8, 9]      # 06–09
    midday_hours  = [10, 11, 12, 13, 14, 15]  # 10–15 (to <16)
    evening_hours = [16, 17]          # 16–17

    name_pool = [
        "Tom Jerry","Mr Muscle","John Cena","Wonder Woman","Bibi Rex",
        "Bruce Wayne","Diana Prince","Peter Parker","Natasha Romanoff","Clark Kent",
        "Tony Stark","Steve Rogers","T'Challa","Harley Quinn","Logan",
        "Arya Stark","Daenerys Targaryen","Frodo Baggins","Lara Croft",
        "Neo","Trinity","Morpheus","Hermione Granger","Katniss Everdeen",
        "Jack Reacher","Ethan Hunt","James Bond","Black Widow","Hawkeye",
        "Shuri","Okoye","M’Baku","Groot","Rocket Raccoon","Gamora",
    ]

    with db_session() as s:
        if not keep:
            _clear_window(s, start, end)

        # We’ll keep a rolling cursor across the name pool
        next_idx = 0
        created_sessions: List[int] = []

        d = start
        while d <= end:
            # Morning: groups of 6 each hour
            for h in morning_hours:
                sid = _ensure_session(s, d, f"{h:02d}:00", capacity=6)
                created_sessions.append(sid)
                for _ in range(6):
                    name, next_idx = _next_name(name_pool, next_idx)
                    wa = _fake_msisdn(next_idx) if assign_wa else None
                    cid = _ensure_client(s, name=name, wa=wa)
                    _ensure_booking(s, cid, sid, "confirmed")

            # Midday: alternate single/duo
            alt_single = True
            for h in midday_hours:
                cap = 1 if alt_single else 2
                sid = _ensure_session(s, d, f"{h:02d}:00", capacity=cap)
                created_sessions.append(sid)
                for _ in range(cap):
                    name, next_idx = _next_name(name_pool, next_idx)
                    wa = _fake_msisdn(next_idx) if assign_wa else None
                    cid = _ensure_client(s, name=name, wa=wa)
                    _ensure_booking(s, cid, sid, "confirmed")
                alt_single = not alt_single

            # Evening: groups of 6 for 16:00 and 17:00
            for h in evening_hours:
                sid = _ensure_session(s, d, f"{h:02d}:00", capacity=6)
                created_sessions.append(sid)
                for _ in range(6):
                    name, next_idx = _next_name(name_pool, next_idx)
                    wa = _fake_msisdn(next_idx) if assign_wa else None
                    cid = _ensure_client(s, name=name, wa=wa)
                    _ensure_booking(s, cid, sid, "confirmed")

            d += timedelta(days=1)

        _recalc_booked_counts(s, created_sessions)

        return jsonify({
            "ok": True,
            "window": {"mon": str(start), "fri": str(end)},
            "sessions_created": len(created_sessions),
            "note": "Morning=6 pax, Midday=alt single/duo, Evening=6 pax",
            "assign_wa": assign_wa,
        }), 200

# ──────────────────────────────────────────────────────────────────────────────
# Dump sessions/bookings for the next N days
# ──────────────────────────────────────────────────────────────────────────────
@diag_bp.get("/diag/dump-week")
def dump_week():
    days = int(request.args.get("days", "7"))
    today = date.today()
    end = today + timedelta(days=days - 1)
    with db_session() as s:
        rows = s.execute(text("""
            SELECT sess.id AS session_id,
                   sess.session_date,
                   sess.start_time,
                   sess.capacity,
                   sess.booked_count,
                   sess.status AS session_status,
                   b.status AS booking_status,
                   c.name AS client_name,
                   c.wa_number
            FROM sessions sess
            LEFT JOIN bookings b ON b.session_id = sess.id
            LEFT JOIN clients c ON c.id = b.client_id
            WHERE sess.session_date BETWEEN :d0 AND :d1
            ORDER BY sess.session_date, sess.start_time, c.name NULLS LAST
        """), {"d0": today, "d1": end}).mappings().all()
    return jsonify({
        "ok": True,
        "window": {"start": str(today), "end": str(end), "days": days},
        "rows": [dict(r) for r in rows],
    }), 200

# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers (SQL)
# ──────────────────────────────────────────────────────────────────────────────
def _ensure_client(s, name: str, wa: Optional[str]) -> int:
    if wa:
        row = s.execute(text("SELECT id FROM clients WHERE wa_number = :wa LIMIT 1"), {"wa": wa}).first()
        if row:
            cid = int(row[0])
            s.execute(text("UPDATE clients SET name = :name WHERE id = :id"), {"name": name, "id": cid})
            return cid
        res = s.execute(text(
            "INSERT INTO clients (name, wa_number) VALUES (:name, :wa) RETURNING id"
        ), {"name": name, "wa": wa}).first()
        return int(res[0])
    row = s.execute(text("SELECT id FROM clients WHERE name = :name LIMIT 1"), {"name": name}).first()
    if row:
        return int(row[0])
    res = s.execute(text("INSERT INTO clients (name) VALUES (:name) RETURNING id"), {"name": name}).first()
    return int(res[0])

def _ensure_session(s, d: date, hhmm: str, capacity: int = 6) -> int:
    row = s.execute(text("""
        SELECT id FROM sessions
        WHERE session_date = :d AND start_time = :t
        LIMIT 1
    """), {"d": d, "t": hhmm}).first()
    if row:
        sid = int(row[0])
        s.execute(text("UPDATE sessions SET capacity = :cap, status = 'scheduled' WHERE id = :id"),
                  {"cap": capacity, "id": sid})
        return sid
    res = s.execute(text("""
        INSERT INTO sessions (session_date, start_time, capacity, booked_count, status)
        VALUES (:d, :t, :cap, 0, 'scheduled')
        RETURNING id
    """), {"d": d, "t": hhmm, "cap": capacity}).first()
    return int(res[0])

def _ensure_booking(s, client_id: int, session_id: int, status: str) -> int:
    row = s.execute(text("""
        SELECT id FROM bookings
        WHERE client_id = :c AND session_id = :s
        LIMIT 1
    """), {"c": client_id, "s": session_id}).first()
    if row:
        bid = int(row[0])
        s.execute(text("UPDATE bookings SET status = :st WHERE id = :id"),
                  {"st": status, "id": bid})
        return bid
    res = s.execute(text("""
        INSERT INTO bookings (client_id, session_id, status)
        VALUES (:c, :s, :st)
        RETURNING id
    """), {"c": client_id, "s": session_id, "st": status}).first()
    return int(res[0])

def _recalc_booked_counts(s, session_ids: List[int]) -> None:
    if not session_ids:
        return
    counts = s.execute(text("""
        SELECT session_id, COUNT(*) AS cnt
        FROM bookings
        WHERE status = 'confirmed' AND session_id = ANY(:ids)
        GROUP BY session_id
    """), {"ids": session_ids}).all()
    by_session = {sid: 0 for sid in session_ids}
    for sid, cnt in counts:
        by_session[int(sid)] = int(cnt)
    for sid, cnt in by_session.items():
        s.execute(text("UPDATE sessions SET booked_count = :cnt WHERE id = :sid"),
                  {"cnt": cnt, "sid": sid})

def _clear_window(s, start: date, end: date) -> None:
    sess_rows = s.execute(text("""
        SELECT id FROM sessions WHERE session_date BETWEEN :d0 AND :d1
    """), {"d0": start, "d1": end}).all()
    if not sess_rows:
        return
    sess_ids = [int(r[0]) for r in sess_rows]
    s.execute(text("DELETE FROM bookings WHERE session_id = ANY(:ids)"), {"ids": sess_ids})
    s.execute(text("DELETE FROM sessions WHERE id = ANY(:ids)"), {"ids": sess_ids})

def _next_monday(d: date) -> date:
    return d + timedelta(days=(0 - d.weekday()) % 7)

def _parse_date(s: str) -> date:
    try:
        y, m, dd = s.split("-")
        return date(int(y), int(m), int(dd))
    except Exception:
        return _next_monday(date.today())

def _next_name(pool: List[str], idx: int) -> Tuple[str, int]:
    name = pool[idx % len(pool)]
    # If we’ve looped around many times, append a suffix to keep names unique-ish
    rounds = idx // len(pool)
    if rounds > 0:
        name = f"{name} #{rounds+1}"
    return name, idx + 1

def _fake_msisdn(n: int) -> str:
    # South Africa-like test range 2784xxxxxxx (not guaranteed valid)
    return f"2784{(1000000 + (n % 8999999))}"
