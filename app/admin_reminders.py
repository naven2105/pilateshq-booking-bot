from __future__ import annotations
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import List, Dict
from sqlalchemy import text

from .config import ADMIN_NUMBERS, TEMPLATE_LANG
from .db import db_session
from . import utils

log = logging.getLogger(__name__)
TZ = ZoneInfo("Africa/Johannesburg")


def _fetch_today_hourly_names() -> Dict[str, List[str]]:
    """
    Dict 'HH:MM' -> [client names...] for today's confirmed bookings.
    """
    today = datetime.now(TZ).date()
    sql = text("""
        SELECT to_char(s.start_time, 'HH24:MI') AS hhmm, c.name AS client_name
        FROM sessions s
        JOIN bookings b ON b.session_id = s.id
        JOIN clients  c ON c.id = b.client_id
        WHERE s.session_date = :today
          AND b.status = 'confirmed'
        ORDER BY s.start_time, c.name
    """)
    by_hour: Dict[str, List[str]] = {}
    with db_session() as s:
        rows = s.execute(sql, {"today": today}).all()
    for hhmm, name in rows:
        by_hour.setdefault(hhmm, []).append(name)
    return by_hour


def _format_admin_summary_line(by_hour: Dict[str, List[str]]) -> str:
    """One-line summary string for admin templates."""
    if not by_hour:
        return "No sessions today — we’re missing you."
    parts: List[str] = []
    for hhmm in sorted(by_hour.keys()):
        names = by_hour[hhmm]
        parts.append(f"{hhmm}({len(names)}): {', '.join(names)}")
    return " • ".join(parts)


def _send_to_admins(tpl_name: str, count: int, details: str, context_label: str) -> int:
    """
    Shared sender for morning/evening admin notifications.
    """
    sent_ok = 0
    langs = [TEMPLATE_LANG or "en", "en_US"]

    for admin in ADMIN_NUMBERS:
        ok = False
        last_status = None
        for lang in langs:
            resp = utils.send_whatsapp_template(
                to=admin,
                name=tpl_name,
                lang=lang,
                variables=[str(count), details],
            )
            status = resp.get("status_code")
            ok = resp.get("ok", False)
            log.info(
                "[%s][send] to=%s tpl=%s lang=%s status=%s ok=%s count=%s",
                context_label, admin, tpl_name, lang, status, ok, count
            )
            if ok:
                sent_ok += 1
                break

        if not ok:
            # fallback text
            title = "Morning Brief" if context_label == "admin-morning" else "20h Recap"
            body = f"PilatesHQ {title}\nTotal time slots today: {count}\n{details}"
            utils.send_whatsapp_text(admin, body)
            log.warning("[%s] fallback text → %s", context_label, admin)

    return sent_ok


def run_admin_morning() -> int:
    """06:00 SAST morning brief (admin_20h00_us template)."""
    by_hour = _fetch_today_hourly_names()
    details = _format_admin_summary_line(by_hour)
    count = len(by_hour)
    return _send_to_admins("admin_20h00_us", count, details, "admin-morning")


def run_admin_daily() -> int:
    """20:00 SAST recap (admin_20h00_us template)."""
    by_hour = _fetch_today_hourly_names()
    details = _format_admin_summary_line(by_hour)
    count = len(by_hour)
    return _send_to_admins("admin_20h00_us", count, details, "admin-daily")
