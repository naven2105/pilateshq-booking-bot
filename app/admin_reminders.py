# app/admin_reminders.py
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
    Returns dict keyed by 'HH:MM' -> [name, name, ...] for today's confirmed bookings.
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
    """
    Builds single-line summary: '06:00(3): A, B, C • 07:00(2): D, E'
    """
    if not by_hour:
        return "No sessions today — we’re missing you."
    parts: List[str] = []
    for hhmm in sorted(by_hour.keys()):
        names = by_hour[hhmm]
        parts.append(f"{hhmm}({len(names)}): {', '.join(names)}")
    return " • ".join(parts)

def run_admin_morning() -> int:
    """
    06:00 SAST morning brief using the approved 'admin_20h00' template.
      {{1}} → count of distinct time slots today
      {{2}} → 'HH:MM(count): names • ...'  (or 'No sessions today — we’re missing you.')
    Returns number of admin messages sent successfully.
    """
    by_hour = _fetch_today_hourly_names()
    details = _format_admin_summary_line(by_hour)
    count = len(by_hour)
    tpl = "admin_20h00"

    sent_ok = 0
    # Try configured template language first, then fallback to en_ZA and en_US, then plain text
    langs = [TEMPLATE_LANG or "en", "en_ZA", "en_US"]
    for admin in ADMIN_NUMBERS:
        ok = False
        last_status = None
        for lang in langs:
            resp = utils.send_whatsapp_template(
                to=admin,
                template=tpl,
                lang=lang,
                variables=[str(count), details],
            )
            last_status = getattr(resp, "status_code", None) if resp else None
            ok = bool(resp and getattr(resp, "ok", False))
            log.info("[admin-morning][send] to=%s tpl=%s lang=%s status=%s ok=%s count=%s",
                     admin, tpl, lang, last_status, ok, count)
            if ok:
                break
        if not ok:
            # Fallback to plain text if template/lang is missing
            body = f"PilatesHQ Morning Brief\nTotal time slots today: {count}\n{details}"
            utils.send_whatsapp_text(admin, body)
            log.warning("[admin-morning] template fallback → text for %s", admin)
        else:
            sent_ok += 1
    log.info("[admin-morning] slots=%s admins=%s sent=%s", count, len(ADMIN_NUMBERS), sent_ok)
    return sent_ok

def run_admin_daily() -> int:
    """
    20:00 SAST recap using the same 'admin_20h00' template.
    Shows today's final schedule line and total distinct time slots.
    """
    by_hour = _fetch_today_hourly_names()
    details = _format_admin_summary_line(by_hour)
    count = len(by_hour)
    tpl = "admin_20h00"

    sent_ok = 0
    langs = [TEMPLATE_LANG or "en", "en_ZA", "en_US"]
    for admin in ADMIN_NUMBERS:
        resp = None
        ok = False
        last_status = None
        for lang in langs:
            resp = utils.send_whatsapp_template(
                to=admin,
                template=tpl,
                lang=lang,
                variables=[str(count), details],
            )
            last_status = getattr(resp, "status_code", None) if resp else None
            ok = bool(resp and getattr(resp, "ok", False))
            log.info("[admin-daily][send] to=%s tpl=%s lang=%s status=%s ok=%s count=%s",
                     admin, tpl, lang, last_status, ok, count)
            if ok:
                break
        if not ok:
            body = f"PilatesHQ 20h Recap\nTotal time slots today: {count}\n{details}"
            utils.send_whatsapp_text(admin, body)
            log.warning("[admin-daily] template fallback → text for %s", admin)
        else:
            sent_ok += 1
    log.info("[admin-daily] slots=%s admins=%s sent=%s", count, len(ADMIN_NUMBERS), sent_ok)
    return sent_ok
