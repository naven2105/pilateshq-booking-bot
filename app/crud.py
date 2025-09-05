# app/crud.py
from __future__ import annotations
from datetime import date
from sqlalchemy import text
from .db import get_session
from .utils import normalize_wa

# ──────────────────────────────────────────────────────────────────────────────
# Clients: list, search, profile, create/update, credits
# ──────────────────────────────────────────────────────────────────────────────

def list_clients(limit: int = 10, offset: int = 0) -> list[dict]:
    with get_session() as s:
        rows = s.execute(
            text("""
                SELECT
                  id,
                  COALESCE(name,'')      AS name,
                  COALESCE(wa_number,'') AS wa_number,
                  COALESCE(plan,'')      AS plan,
                  COALESCE(credits,0)    AS credits
                FROM clients
                ORDER BY COALESCE(name,''), id
                LIMIT :lim OFFSET :off
            """),
            {"lim": int(limit), "off": int(offset)},
        ).mappings().all()
        return [dict(r) for r in rows]

def find_clients_by_name(q: str, limit: int = 10, offset: int = 0) -> list[dict]:
    q = (q or "").strip()
    if not q:
        return list_clients(limit=limit, offset=offset)
    with get_session() as s:
        rows = s.execute(
            text("""
                SELECT
                  id,
                  COALESCE(name,'')      AS name,
                  COALESCE(wa_number,'') AS wa_number,
                  COALESCE(plan,'')      AS plan,
                  COALESCE(credits,0)    AS credits
                FROM clients
                WHERE LOWER(COALESCE(name,'')) LIKE LOWER(:needle)
                ORDER BY COALESCE(name,''), id
                LIMIT :lim OFFSET :off
            """),
            {"needle": f"%{q}%", "lim": int(limit), "off": int(offset)},
        ).mappings().all()
        return [dict(r) for r in rows]

def get_client_profile(client_id: int) -> dict | None:
    with get_session() as s:
        row = s.execute(
            text("""
                SELECT
                  id,
                  COALESCE(name,'')           AS name,
                  COALESCE(wa_number,'')      AS wa_number,
                  COALESCE(plan,'')           AS plan,
                  COALESCE(credits,0)         AS credits,
                  birthday_day,
                  birthday_month,
                  COALESCE(medical_notes,'')  AS medical_notes
                FROM clients
                WHERE id = :cid
            """),
            {"cid": client_id},
        ).mappings().first()
        return dict(row) if row else None

def get_or_create_client(wa_number: str) -> dict:
    wa = normalize_wa(wa_number)
    with get_session() as s:
        row = s.execute(text("SELECT * FROM clients WHERE wa_number = :w"), {"w": wa}).mappings().first()
        if row:
            return dict(row)
        row = s.execute(
            text("""
              INSERT INTO clients (wa_number, name, plan, credits)
              VALUES (:w, NULL, '1x', 0)
              RETURNING *
            """),
            {"w": wa},
        ).mappings().first()
        return dict(row)

def create_client(name: str, wa_number: str) -> dict | None:
    wa = normalize_wa(wa_number)
    with get_session() as s:
        row = s.execute(
            text("""
                INSERT INTO clients (wa_number, name, plan, credits)
                VALUES (:w, :n, '1x', 0)
                ON CONFLICT (wa_number) DO UPDATE SET name = EXCLUDED.name
                RETURNING *
            """),
            {"w": wa, "n": name.strip()[:120]},
        ).mappings().first()
        return dict(row) if row else None

def adjust_client_credits(client_id: int, delta: int) -> None:
    with get_session() as s:
        s.execute(
            text("UPDATE clients SET credits = COALESCE(credits,0) + :d WHERE id = :cid"),
            {"d": int(delta), "cid": client_id},
        )

def update_client_dob(client_id: int, day: int, month: int) -> None:
    with get_session() as s:
        s.execute(
            text("UPDATE clients SET birthday_day = :d, birthday_month = :m WHERE id = :cid"),
            {"d": int(day), "m": int(month), "cid": client_id},
        )

def update_client_medical(client_id: int, note: str, append: bool = True) -> None:
    note = (note or "").strip()
    with get_session() as s:
        if append:
            s.execute(
                text("""
                  UPDATE clients
                  SET medical_notes = CONCAT(COALESCE(medical_notes,''), CASE WHEN COALESCE(medical_notes,'')='' THEN '' ELSE '\n' END, :n)
                  WHERE id = :cid
                """),
                {"n": note[:500], "cid": client_id},
            )
        else:
            s.execute(
                text("UPDATE clients SET medical_notes = :n WHERE id = :cid"),
                {"n": note[:500], "cid": client_id},
            )

# ──────────────────────────────────────────────────────────────────────────────
# Sessions & bookings: find/cancel/no-show
# ──────────────────────────────────────────────────────────────────────────────

def find_session_by_date_time(session_date: date, hhmm: str) -> dict | None:
    with get_session() as s:
        row = s.execute(
            text("""
                SELECT *
                FROM sessions
                WHERE session_date = :d AND start_time = :t
                LIMIT 1
            """),
            {"d": session_date, "t": hhmm},
        ).mappings().first()
        return dict(row) if row else None

def cancel_next_booking_for_client(client_id: int) -> bool:
    """
    Marks the soonest future confirmed booking for this client as 'cancelled'.
    Returns True if something was cancelled.
    """
    with get_session() as s:
        row = s.execute(
            text("""
                WITH now_local AS (
                  SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE 'Africa/Johannesburg') AS ts
                ),
                next_b AS (
                  SELECT b.id
                  FROM bookings b
                  JOIN sessions s ON s.id = b.session_id
                  , now_local
                  WHERE b.client_id = :cid
                    AND b.status = 'confirmed'
                    AND (s.session_date + s.start_time) > now_local.ts
                  ORDER BY s.session_date, s.start_time
                  LIMIT 1
                )
                UPDATE bookings
                SET status = 'cancelled'
                WHERE id IN (SELECT id FROM next_b)
                RETURNING id
            """),
            {"cid": client_id},
        ).mappings().first()
        return bool(row)

def mark_no_show_today(client_id: int) -> bool:
    """
    Marks today's confirmed booking for this client as 'no_show' if one exists.
    Returns True if updated.
    """
    with get_session() as s:
        row = s.execute(
            text("""
                WITH today_local AS (
                  SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE 'Africa/Johannesburg')::date AS d
                ),
                tgt AS (
                  SELECT b.id
                  FROM bookings b
                  JOIN sessions s ON s.id = b.session_id
                  , today_local
                  WHERE b.client_id = :cid
                    AND b.status = 'confirmed'
                    AND s.session_date = today_local.d
                  ORDER BY s.start_time
                  LIMIT 1
                )
                UPDATE bookings
                SET status = 'no_show'
                WHERE id IN (SELECT id FROM tgt)
                RETURNING id
            """),
            {"cid": client_id},
        ).mappings().first()
        return bool(row)

# ──────────────────────────────────────────────────────────────────────────────
# Query: next upcoming booking for a specific WhatsApp number
# ──────────────────────────────────────────────────────────────────────────────

def find_next_upcoming_booking_by_wa(wa_number: str) -> dict | None:
    """
    Return the soonest future confirmed booking for this WA number (Africa/Johannesburg local time),
    or None if not found.
    """
    wa = normalize_wa(wa_number)
    with get_session() as s:
        row = s.execute(
            text("""
                WITH now_local AS (
                  SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE 'Africa/Johannesburg') AS ts
                )
                SELECT
                  b.id                 AS booking_id,
                  s.id                 AS session_id,
                  s.session_date       AS session_date,
                  s.start_time         AS start_time,
                  c.id                 AS client_id,
                  COALESCE(c.name,'')  AS name,
                  COALESCE(c.wa_number,'') AS wa_number
                FROM bookings b
                JOIN sessions s ON s.id = b.session_id
                JOIN clients  c ON c.id = b.client_id
                , now_local
                WHERE c.wa_number = :wa
                  AND b.status = 'confirmed'
                  AND (s.session_date + s.start_time) > now_local.ts
                ORDER BY s.session_date, s.start_time
                LIMIT 1
            """),
            {"wa": wa},
        ).mappings().first()
        return dict(row) if row else None
