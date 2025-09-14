# app/client_reminders.py
"""
Client Reminders (template-based, aligned to approved templates)
----------------------------------------------------------------
Uses:
- session_tomorrow          ({{1}} = time only, lang en_US)
- session_next_hour         ({{1}} = time only, lang en)
- weekly_template_message   ({{1}} = name, {{2}} = single-line list, lang en)

Notes:
- Casts ENUM booking status to text for Postgres comparisons.
- Sanitizes template vars to avoid error 132018 (no newlines/tabs, collapse spaces).
"""

from __future__ import annotations
import logging
import re
from datetime import date, datetime, timedelta
from typing import Dict, List, Tuple

from sqlalchemy import and_, cast, String

from .db import db_session
from .models import Client, Booking, Session
from . import utils, config

log = logging.getLogger(__name__)

# ── Template names / languages (match your WhatsApp Manager setup) ───────────
T_CLIENT_TOMORROW       = getattr(config, "CLIENT_TEMPLATE_TOMORROW", "session_tomorrow")
T_CLIENT_TOMORROW_LANG  = getattr(config, "CLIENT_TEMPLATE_TOMORROW_LANG", "en_US")  # English (US)

T_CLIENT_NEXT_HOUR      = getattr(config, "CLIENT_TEMPLATE_NEXT_HOUR", "session_next_hour")
T_CLIENT_NEXT_HOUR_LANG = getattr(config, "CLIENT_TEMPLATE_NEXT_HOUR_LANG", "en")    # English

T_CLIENT_WEEKLY         = getattr(config, "CLIENT_TEMPLATE_WEEKLY", "weekly_template_message")
T_CLIENT_WEEKLY_LANG    = getattr(config, "CLIENT_TEMPLATE_WEEKLY_LANG", "en")       # English

# ── Sanitizers (avoid WhatsApp 132018) ────────────────────────────────────────
_SPACE_COLLAPSE = re.compile(r"\s+")
_FIVE_SPACES_OR_MORE = re.compile(r" {5,}")

def _sanitize_param(text_val: str) -> str:
    """Remove newlines/tabs, collapse whitespace, cap at 1024 chars."""
    if not text_val:
        return ""
    t = text_val.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    t = _SPACE_COLLAPSE.sub(" ", t)
    t = _FIVE_SPACES_OR_MORE.sub("    ", t)  # max four spaces in a row
    return t.strip()[:1024]

def _join_single_line(items: List[str]) -> str:
    """Join items with a bullet ' • ' and sanitize to a single line."""
    flat = " • ".join([_sanitize_param(i) for i in items if i])
    return _sanitize_param(flat)

# ── Formatters ────────────────────────────────────────────────────────────────
def _fmt_time(t) -> str:
    try:
        return t.strftime("%H:%M")
    except Exception:
        return str(t)

def _fmt_weekly_item(d: date, t) -> str:
    """e.g., 'Mon 16 Sep 09:00'."""
    try:
        return f"{d.strftime('%a %d %b')} {_fmt_time(t)}"
    except Exception:
        return f"{d} {_fmt_time(t)}"

# ──────────────────────────────────────────────────────────────────────────────
# Night-before reminders (run ~20:00) → session_tomorrow ({{1}} = time)
# ──────────────────────────────────────────────────────────────────────────────
def run_client_tomorrow() -> int:
    tomorrow = date.today() + timedelta(days=1)
    try:
        rows: List[Tuple[str, object]] = (
            db_session.query(Client.wa_number, Session.start_time)
            .join(Booking, Booking.client_id == Client.id)
            .join(Session, Booking.session_id == Session.id)
            .filter(
                and_(
                    cast(Booking.status, String) == "confirmed",
                    Session.session_date == tomorrow,
                    Client.wa_number.isnot(None),
                )
            )
            .order_by(Session.start_time)
            .all()
        )

        sent = 0
        for wa, stime in rows:
            res = utils.send_whatsapp_template(
                to=wa,
                template_name=T_CLIENT_TOMORROW,
                lang_code=T_CLIENT_TOMORROW_LANG,
                body_params=[_sanitize_param(_fmt_time(stime))],
            )
            sent += 1 if res.get("status_code", 0) > 0 else 0

        log.info("[reminders:tomorrow] rows=%s sent=%s", len(rows), sent)
        return sent

    except Exception:
        log.exception("[reminders:tomorrow] query failed")
        db_session.rollback()
        raise

# ──────────────────────────────────────────────────────────────────────────────
# 1-hour reminders (run hourly) → session_next_hour ({{1}} = time)
# ──────────────────────────────────────────────────────────────────────────────
def run_client_next_hour() -> int:
    now = datetime.now()
    target = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    next_time = target.time()
    today = date.today()
    try:
        rows: List[Tuple[str, object]] = (
            db_session.query(Client.wa_number, Session.start_time)
            .join(Booking, Booking.client_id == Client.id)
            .join(Session, Booking.session_id == Session.id)
            .filter(
                and_(
                    cast(Booking.status, String) == "confirmed",
                    Session.session_date == today,
                    Session.start_time == next_time,
                    Client.wa_number.isnot(None),
                )
            )
            .order_by(Session.start_time)
            .all()
        )

        sent = 0
        for wa, stime in rows:
            res = utils.send_whatsapp_template(
                to=wa,
                template_name=T_CLIENT_NEXT_HOUR,
                lang_code=T_CLIENT_NEXT_HOUR_LANG,
                body_params=[_sanitize_param(_fmt_time(stime))],
            )
            sent += 1 if res.get("status_code", 0) > 0 else 0

        log.info("[reminders:next-hour] time=%s rows=%s sent=%s", _fmt_time(next_time), len(rows), sent)
        return sent

    except Exception:
        log.exception("[reminders:next-hour] query failed")
        db_session.rollback()
        raise

# ──────────────────────────────────────────────────────────────────────────────
# Weekly preview (Sun 18:00) → weekly_template_message ({{1}} name, {{2}} list)
# ──────────────────────────────────────────────────────────────────────────────
def run_client_weekly() -> int:
    start = date.today()
    end = start + timedelta(days=7)
    try:
        rows: List[Tuple[str, str, date, object]] = (
            db_session.query(
                Client.wa_number,
                Client.name,
                Session.session_date,
                Session.start_time,
            )
            .join(Booking, Booking.client_id == Client.id)
            .join(Session, Booking.session_id == Session.id)
            .filter(
                and_(
                    cast(Booking.status, String) == "confirmed",
                    Session.session_date.between(start, end),
                    Client.wa_number.isnot(None),
                )
            )
            .order_by(Client.wa_number, Session.session_date, Session.start_time)
            .all()
        )

        # Group by recipient
        by_client: Dict[str, Dict[str, List[str]]] = {}
        for wa, name, sdate, stime in rows:
            entry = _fmt_weekly_item(sdate, stime)
            bucket = by_client.setdefault(wa, {"name": name or "there", "items": []})
            bucket["items"].append(entry)

        sent = 0
        for wa, payload in by_client.items():
            name = _sanitize_param(payload["name"])
            items_flat = _join_single_line(payload["items"]) if payload["items"] else "No sessions in the next 7 days."
            res = utils.send_whatsapp_template(
                to=wa,
                template_name=T_CLIENT_WEEKLY,
                lang_code=T_CLIENT_WEEKLY_LANG,
                body_params=[name, items_flat],
            )
            sent += 1 if res.get("status_code", 0) > 0 else 0

        log.info("[reminders:weekly] clients=%s sent=%s", len(by_client), sent)
        return sent

    except Exception:
        log.exception("[reminders:weekly] query failed")
        db_session.rollback()
        raise
