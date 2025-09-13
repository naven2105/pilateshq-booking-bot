# app/admin_reminders.py
from __future__ import annotations
import logging
from sqlalchemy import text
from .db import get_session
from .utils import normalize_wa
from .config import TZ_NAME, ADMIN_NUMBERS
from .templates import send_whatsapp_template
from . import crud

# ─────────────────────────────────────────────
# SQL helpers
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

# ─────────────────────────────────────────────
# Formatting
# ─────────────────────────────────────────────

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
# Core senders
# ─────────────────────────────────────────────

def _send_admin_template(template_name: str, params: list[str]) -> None:
    for admin in ADMIN_NUMBERS:
        to = normalize_wa(admin)
        send_whatsapp_template(
            to,
            template_name=template_name,
            lang="en_ZA",
            components=[{"type": "body", "parameters": [{"type": "text", "text": p} for p in params]}]
        )

def run_admin_tick() -> None:
    """
    Hourly admin summary → uses approved template `admin_hourly_update`.
    """
    today = _rows_today(upcoming_only=True)
    body = _fmt_rows(today)

    # Use template params: {{1}} = next session time, {{2}} = session details
    next_time = today[0]["start_time"].strftime("%H:%M") if today else "—"
    params = [next_time, body]

    _send_admin_template("admin_hourly_update", params)

    crud.inbox_upsert(
        kind="hourly",
        title="Hourly update",
        body=body,
        source="cron",
        status="open",
        is_unread=True,
        action_required=False,
        digest=f"hourly-{body[:20]}",
    )
    logging.info("[ADMIN] hourly update sent + inbox")

def run_admin_daily() -> None:
    """
    Daily admin recap (20:00) → uses approved template `admin_20h00`.
    """
    today = _rows_today(upcoming_only=False)
    body = _fmt_rows(today)

    total = len(today)
    params = [str(total), body]

    _send_admin_template("admin_20h00", params)

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
