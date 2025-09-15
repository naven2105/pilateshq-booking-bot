# app/admin_reminders.py
from __future__ import annotations
import logging
from datetime import date
from typing import Dict, List, Tuple
from sqlalchemy import text

from .db import get_session
from .config import ADMIN_NUMBERS
from . import utils

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _fmt_d(d: date) -> str:
    return d.strftime("%a %d %b")

def _flatten_pairs(pairs: List[Tuple[str, List[str]]]) -> str:
    """
    Build a SINGLE-LINE summary acceptable for WA template param:
    "06:00(3): Alice, Ben, Cara • 07:00(2): Dan, Emma • ..."
    """
    chunks: List[str] = []
    for hhmm, names in pairs:
        who = ", ".join(names) if names else "-"
        chunks.append(f"{hhmm}({len(names)}): {who}")
    return " • ".join(chunks) if chunks else "No sessions booked today"

def _cap_line(s: str, max_len: int = 900) -> str:
    """Cap the detail line to stay within WA param limits (~1024), with soft buffer."""
    if len(s) <= max_len:
        return s
    return s[: max_len - 12].rstrip() + " … +more"

def _load_today_buckets(the_day: date) -> Tuple[List[Tuple[str, List[str]]], int]:
    """
    Returns (pairs, session_count) where:
      - pairs: [(HH:MM, [client names]), ...] for CONFIRMED bookings only.
      - session_count: number of distinct start_time buckets that have at least one confirmed booking.
    """
    with get_session() as s:
        rows = s.execute(
            text(
                """
                SELECT sessions.start_time, clients.name
                FROM sessions
                JOIN bookings ON bookings.session_id = sessions.id
                JOIN clients  ON clients.id = bookings.client_id
                WHERE sessions.session_date = :d
                  AND bookings.status = 'confirmed'
                ORDER BY sessions.start_time, clients.name
                """
            ),
            {"d": the_day},
        ).fetchall()

    bucket: Dict[str, List[str]] = {}
    for start_time, client_name in rows:
        hhmm = str(start_time)[:5]  # 'HH:MM:SS' -> 'HH:MM'
        bucket.setdefault(hhmm, []).append(client_name)

    pairs = sorted(bucket.items(), key=lambda kv: kv[0])
    session_count = len(pairs)
    return pairs, session_count

# ──────────────────────────────────────────────────────────────────────────────
# 06:00 Admin Morning Brief  (uses admin_20h00)
# ──────────────────────────────────────────────────────────────────────────────

def run_admin_morning(today: date | None = None) -> int:
    """
    Compile today's CONFIRMED sessions grouped by hour with client names and
    send ONE message to each admin using the 'admin_20h00' template.
    Params: {{1}} = count of booked session slots today, {{2}} = compact details line.
    """
    the_day = today or date.today()
    pairs, session_count = _load_today_buckets(the_day)
    details = _cap_line(_flatten_pairs(pairs))
    count_str = str(session_count)

    ok_count = 0
    for admin in ADMIN_NUMBERS:
        ok, status, resp, chosen_lang = utils.send_whatsapp_template(
            to=admin,
            template_name="admin_20h00",
            params=[count_str, details],
            # Prefer the approved language first to avoid 132001 errors.
            lang_prefer=["en_ZA", "en", "en_US"],
        )
        if not ok:
            # Fallback: concise single-line text
            text_line = f"Daily schedule { _fmt_d(the_day) }: sessions={count_str}; {details}"
            ok, status, resp = utils.send_whatsapp_text(admin, text_line)
        log.info("[admin-morning][send] to=%s status=%s ok=%s lang=%s",
                 admin, status, ok, chosen_lang if ok else None)
        ok_count += 1 if ok else 0

    # Cron heartbeat
    try:
        from .diag import note_cron_run
        note_cron_run("admin-morning")
    except Exception:
        pass

    log.info("[admin-morning] %s sent=%s", _fmt_d(the_day), ok_count)
    return ok_count

# ──────────────────────────────────────────────────────────────────────────────
# 20:00 Admin Recap  (also uses admin_20h00)
# ──────────────────────────────────────────────────────────────────────────────

def run_admin_daily(today: date | None = None) -> int:
    """
    20:00 recap using the same 'admin_20h00' template.
    We reuse the CONFIRMED-by-hour with names format for {{2}} to keep consistency.
    """
    the_day = today or date.today()
    pairs, session_count = _load_today_buckets(the_day)
    details = _cap_line(_flatten_pairs(pairs))
    count_str = str(session_count)

    ok_total = 0
    for admin in ADMIN_NUMBERS:
        ok, status, resp, chosen_lang = utils.send_whatsapp_template(
            to=admin,
            template_name="admin_20h00",
            params=[count_str, details],
            lang_prefer=["en_ZA", "en", "en_US"],
        )
        if not ok:
            text_line = f"Today { _fmt_d(the_day) }: sessions={count_str}; {details}"
            ok, status, resp = utils.send_whatsapp_text(admin, text_line)
        log.info("[admin-daily][send] to=%s status=%s ok=%s lang=%s",
                 admin, status, ok, chosen_lang if ok else None)
        ok_total += 1 if ok else 0

    try:
        from .diag import note_cron_run
        note_cron_run("admin-daily")
    except Exception:
        pass

    log.info("[admin-daily] %s sent=%s", _fmt_d(the_day), ok_total)
    return ok_total
