# app/client_reminders.py
from __future__ import annotations
import logging
from sqlalchemy import text
from .db import get_session
from .utils import normalize_wa
from .config import TZ_NAME, TEMPLATE_LANG
from .templates import send_template  # helper to send template messages

# ─────────────────────────────────────────────
# DB Helpers
# ─────────────────────────────────────────────

def _client_week_sessions() -> list[dict]:
    """
    Fetch all clients who have confirmed bookings for the next 7 days.
    Returns rows with client_id, client_name, wa_number, session_date, start_time.
    """
    sql = """
        WITH now_local AS (
            SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE :tz) AS ts
        )
        SELECT 
            c.id AS client_id,
            COALESCE(NULLIF(c.name,''), 'Guest') AS client_name,
            c.wa_number,
            s.session_date,
            s.start_time
        FROM bookings b
        JOIN sessions s ON s.id = b.session_id
        JOIN clients c ON c.id = b.client_id
        , now_local
        WHERE b.status = 'confirmed'
          AND s.session_date >= (now_local.ts)::date
          AND s.session_date < ((now_local.ts)::date + interval '7 days')
        ORDER BY c.id, s.session_date, s.start_time
    """
    with get_session() as s:
        return [dict(r) for r in s.execute(text(sql), {"tz": TZ_NAME}).mappings().all()]

# ─────────────────────────────────────────────
# Format Helpers
# ─────────────────────────────────────────────

def _fmt_weekly_sessions(rows: list[dict]) -> dict[int, dict]:
    """
    Group sessions by client_id → {client_name, wa_number, sessions_list}.
    """
    out: dict[int, dict] = {}
    for r in rows:
        cid = r["client_id"]
        if cid not in out:
            out[cid] = {
                "name": r["client_name"],
                "wa_number": r["wa_number"],
                "sessions": []
            }
        day = r["session_date"].strftime("%A")   # e.g. "Tuesday"
        time = str(r["start_time"])[:5]          # "08:00"
        out[cid]["sessions"].append(f"• {day} {time}")
    return out

# ─────────────────────────────────────────────
# Core Weekly Reminder
# ─────────────────────────────────────────────

def run_client_weekly() -> int:
    """
    Send weekly schedule to each client with confirmed sessions in the next 7 days.
    Returns number of clients messaged.
    """
    rows = _client_week_sessions()
    grouped = _fmt_weekly_sessions(rows)

    sent_count = 0
    for cid, info in grouped.items():
        if not info["sessions"]:
            continue
        to = normalize_wa(info["wa_number"])
        name = info["name"]
        sessions_str = "\n".join(info["sessions"])
        try:
            send_template(
                to=to,
                template_name="session_weekly",
                lang=TEMPLATE_LANG,
                components=[{"type": "body", "parameters": [
                    {"type": "text", "text": name},
                    {"type": "text", "text": sessions_str},
                ]}],
            )
            logging.info(f"[WEEKLY] Sent weekly schedule to {name} ({to})")
            sent_count += 1
        except Exception:
            logging.exception(f"[WEEKLY] Failed to send to {name} ({to})")
    return sent_count
