# app/admin_reminders.py
from __future__ import annotations
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import List, Dict

from sqlalchemy import text

from .config import ADMIN_NUMBERS
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


def _fetch_tomorrow_hourly_names() -> Dict[str, List[str]]:
    """
    Dict 'HH:MM' -> [client names...] for tomorrow’s confirmed bookings.
    """
    tomorrow = datetime.now(TZ).date().replace(day=datetime.now(TZ).day + 1)
    sql = text("""
        SELECT to_char(s.start_time, 'HH24:MI') AS hhmm, c.name AS client_name
        FROM sessions s
        JOIN bookings b ON b.session_id = s.id
        JOIN clients  c ON c.id = b.client_id
        WHERE s.session_date = :tomorrow
          AND b.status = 'confirmed'
        ORDER BY s.start_time, c.name
    """)
    by_hour: Dict[str, List[str]] = {}
    with db_session() as s:
        rows = s.execute(sql, {"tomorrow": tomorrow}).all()
    for hhmm, name in rows:
        by_hour.setdefault(hhmm, []).append(name)
    return by_hour


def _format_admin_summary_line(by_hour: Dict[str, List[str]]) -> str:
    """
    One-line summary: '06:00(3): A, B, C • 07:00(2): D, E'
    """
    if not by_hour:
        return "No sessions scheduled."
    parts: List[str] = []
    for hhmm in sorted(by_hour.keys()):
        names = by_hour[hhmm]
        parts.append(f"{hhmm}({len(names)}): {', '.join(names)}")
    return " • ".join(parts)


def _send_to_admins(tpl_name: str, count: int, details: str, context_label: str) -> int:
    """
    Send using US-approved templates only.
    """
    sent_ok = 0
    for admin in ADMIN_NUMBERS:
        resp = utils.send_whatsapp_template(
            admin,
            tpl_name,
            "en_US",   # ✅ only US language
            [str(count), details],
        )
        ok = bool(resp.get("ok"))
        status = resp.get("status_code")
        log.info(
            "[%s][send] to=%s tpl=%s lang=en_US status=%s ok=%s count=%s",
            context_label, admin, tpl_name, status, ok, count
        )
        if ok:
            sent_ok += 1
        else:
            # fallback plain text
            body = f"PilatesHQ {context_label}\nTotal sessions: {count}\n{details}"
            utils.send_whatsapp_text(admin, body)
            log.warning("[%s] template fallback → text for %s", context_label, admin)
    return sent_ok


def run_admin_morning() -> int:
    """
    06:00 SAST morning brief using 'admin_morning_us' template.
    """
    by_hour = _fetch_today_hourly_names()
    details = _format_admin_summary_line(by_hour)
    count = len(by_hour)
    return _send_to_admins("admin_morning_us", count, details, "admin-morning")


def run_admin_daily() -> int:
    """
    20:00 SAST evening preview using 'admin_20h00_us' template.
    """
    by_hour = _fetch_tomorrow_hourly_names()
    details = _format_admin_summary_line(by_hour)
    count = len(by_hour)
    return _send_to_admins("admin_20h00_us", count, details, "admin-daily")
