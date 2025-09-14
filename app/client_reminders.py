# app/client_reminders.py
"""
Client Reminders (template-based, aligned to your approved templates)
--------------------------------------------------------------------
Uses:
- session_tomorrow          ({{1}} time only)
- session_next_hour         ({{1}} time only)
- weekly_template_message   ({{1}} client name, {{2}} bullet list of sessions)

Fixes:
- Casts ENUM booking status to text for Postgres comparisons.
- Template sends work outside WhatsApp's 24h window.
"""

import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Tuple

from sqlalchemy import and_, cast, String

from .db import db_session
from .models import Client, Booking, Session
from . import utils, config

log = logging.getLogger(__name__)

# Template names / languages (match what you showed in WhatsApp Manager)
T_CLIENT_TOMORROW       = getattr(config, "CLIENT_TEMPLATE_TOMORROW", "session_tomorrow")
T_CLIENT_TOMORROW_LANG  = getattr(config, "CLIENT_TEMPLATE_TOMORROW_LANG", "en_US")  # your template shows English (US)

T_CLIENT_NEXT_HOUR      = getattr(config, "CLIENT_TEMPLATE_NEXT_HOUR", "session_next_hour")
T_CLIENT_NEXT_HOUR_LANG = getattr(config, "CLIENT_TEMPLATE_NEXT_HOUR_LANG", "en")    # English

T_CLIENT_WEEKLY         = getattr(config, "CLIENT_TEMPLATE_WEEKLY", "weekly_template_message")
T_CLIENT_WEEKLY_LANG    = getattr(config, "CLIENT_TEMPLATE_WEEKLY_LANG", "en")       # English


def _fmt_date(d: date) -> str:
    try:
        return d.strftime("%Y-%m-%d")
    except Exception:
        return str(d)


def _fmt_time(t) -> str:
    try:
        return t.strftime("%H:%M")
    except Exception:
        return str(t)


# ──────────────────────────────────────────────────────────────────────────────
# Night-before reminders (run around 20:00) → session_tomorrow ({{1}} = time)
# ──────────────────────────────────────────────────────────────────────────────
def run_client_tomorrow() -> int:
    tomorrow = date.today() + timedelta(days=1)

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
        time_str = _fmt_time(stime)
        res = utils.send_whatsapp_template(
            to=wa,
            template_name=T_CLIENT_TOMORROW,
            lang_code=T_CLIENT_TOMORROW_LANG,
            body_params=[time_str],  # template expects only time
        )
        sent += 1 if res.get("status_code", 0) > 0 else 0

    log.info("[reminders:tomorrow] rows=%s sent=%s", len(rows), sent)
    return sent


# ──────────────────────────────────────────────────────────────────────────────
# 1-hour reminders (run hourly) → session_next_hour ({{1}} = time)
# ──────────────────────────────────────────────────────────────────────────────
def run_client_next_hour() -> int:
    now = datetime.now()
    target = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    next_time = target.time()
    today = date.today()

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
        time_str = _fmt_time(stime)
        res = utils.send_whatsapp_template(
            to=wa,
            template_name=T_CLIENT_NEXT_HOUR,
            lang_code=T_CLIENT_NEXT_HOUR_LANG,
            body_params=[time_str],  # template expects only time
        )
        sent += 1 if res.get("status_code", 0) > 0 else 0

    log.info("[reminders:next-hour] time=%s rows=%s sent=%s", _fmt_time(next_time), len(rows), sent)
    return sent


# ──────────────────────────────────────────────────────────────────────────────
# Weekly preview (Sun 18:00) → weekly_template_message ({{1}} name, {{2}} list)
# ──────────────────────────────────────────────────────────────────────────────
def run_client_weekly() -> int:
    start = date.today()
    end = start + timedelta(days=7)

    rows: List[Tuple[str, str, date, object]] = (
        db_session.query(Client.wa_number, Client.name, Session.session_date, Session.start_time)
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

    by_client: Dict[str, Dict[str, List[Tuple[date, object]]]] = {}
    for wa, name, sdate, stime in rows:
        by_client.setdefault(wa, {"name": name or "there", "items": []})
        by_client[wa]["items"].append((sdate, stime))

    sent = 0
    for wa, payload in by_client.items():
        name = payload["name"]
        lines = []
        for sdate, stime in payload["items"]:
            # Example: "Mon 16 Sep at 09:00"
            dow = sdate.strftime("%a")
            dstr = sdate.strftime("%d %b")
            tstr = _fmt_time(stime)
            lines.append(f"- {dow} {dstr} at {tstr}")
        body_list = "\n".join(lines) if lines else "No sessions in the next 7 days."

        res = utils.send_whatsapp_template(
            to=wa,
            template_name=T_CLIENT_WEEKLY,
            lang_code=T_CLIENT_WEEKLY_LANG,
            body_params=[name, body_list],
        )
        sent += 1 if res.get("status_code", 0) > 0 else 0

    log.info("[reminders:weekly] clients=%s sent=%s", len(by_client), sent)
    return sent
