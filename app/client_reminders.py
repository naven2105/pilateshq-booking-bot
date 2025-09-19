# app/client_reminders.py
from __future__ import annotations

import logging
from datetime import datetime, date, time, timedelta
from typing import List, Tuple

from sqlalchemy.orm import Session as OrmSession

from .db import db_session
from .models import Client, Session, Booking
from . import utils
from .config import TEMPLATE_LANG, ADMIN_NUMBERS

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _fmt_hhmm(t: time) -> str:
    return t.strftime("%H:%M")

def _fmt_item(d: date, t: time) -> str:
    return f"{d.strftime('%a %d %b')} {t.strftime('%H:%M')}"

def _clean_one_line(s: str) -> str:
    return " ".join((s or "").split())

def _lang_candidates(preferred: str | None) -> List[str]:
    cand = [x for x in [preferred, "en", "en_US", "en_ZA"] if x]
    seen, out = set(), []
    for c in cand:
        if c not in seen:
            out.append(c)
            seen.add(c)
    return out

def _send_template_with_fallback(
    to: str,
    template: str,
    variables: dict,
    preferred_lang: str | None,
) -> bool:
    for lang in _lang_candidates(preferred_lang):
        ok, status, _ = utils.send_template(to=to, template=template, lang=lang, variables=variables)
        log.info("[tpl-send] to=%s tpl=%s lang=%s status=%s ok=%s", to, template, lang, status, ok)
        if ok:
            return True
    return False

# ──────────────────────────────────────────────────────────────────────────────
# Night-before (tomorrow) reminders
# ──────────────────────────────────────────────────────────────────────────────

def run_client_tomorrow() -> int:
    tomorrow = date.today() + timedelta(days=1)
    sent = 0
    with db_session() as s:  # type: OrmSession
        rows: List[Tuple[str, time]] = (
            s.query(Client.wa_number, Session.start_time)
            .join(Booking, Booking.client_id == Client.id)
            .join(Session, Session.id == Booking.session_id)
            .filter(
                Booking.status == "confirmed",
                Session.session_date == tomorrow,
                Client.wa_number.isnot(None),
                ~Client.wa_number.in_(ADMIN_NUMBERS),   # exclude admins
            )
            .order_by(Session.start_time.asc())
            .all()
        )
        for wa, tt in rows:
            ok = _send_template_with_fallback(
                to=wa,
                template="client_session_tomorrow_us",
                variables={"1": _fmt_hhmm(tt)},
                preferred_lang=TEMPLATE_LANG,
            )
            sent += 1 if ok else 0
    log.info("[client-tomorrow] date=%s candidates=%s sent=%s", tomorrow.isoformat(), len(rows), sent)
    return sent

# ──────────────────────────────────────────────────────────────────────────────
# 1-hour reminders
# ──────────────────────────────────────────────────────────────────────────────

def run_client_next_hour() -> int:
    now = datetime.now()
    today = now.date()
    in_one_hour = (now + timedelta(hours=1)).time()
    start_t = now.time()
    end_t = in_one_hour

    sent = 0
    with db_session() as s:
        rows: List[Tuple[str, time]] = (
            s.query(Client.wa_number, Session.start_time)
            .join(Booking, Booking.client_id == Client.id)
            .join(Session, Session.id == Booking.session_id)
            .filter(
                Booking.status == "confirmed",
                Session.session_date == today,
                Session.start_time >= start_t,
                Session.start_time <= end_t,
                Client.wa_number.isnot(None),
                ~Client.wa_number.in_(ADMIN_NUMBERS),   # exclude admins
            )
            .order_by(Session.start_time.asc())
            .all()
        )
        for wa, tt in rows:
            ok = _send_template_with_fallback(
                to=wa,
                template="client_session_next_hour_us",
                variables={"1": _fmt_hhmm(tt)},
                preferred_lang=TEMPLATE_LANG,
            )
            sent += 1 if ok else 0
    log.info("[client-next-hour] window=%s-%s candidates=%s sent=%s", start_t, end_t, len(rows), sent)
    return sent

# ──────────────────────────────────────────────────────────────────────────────
# Weekly preview (Sunday 18:00 SAST)
# ──────────────────────────────────────────────────────────────────────────────

def run_client_weekly(window_days: int = 7) -> int:
    start = date.today()
    end = start + timedelta(days=max(1, window_days) - 1)
    sent = 0

    with db_session() as s:  # type: OrmSession
        clients: List[Client] = (
            s.query(Client)
            .filter(
                Client.wa_number.isnot(None),
                ~Client.wa_number.in_(ADMIN_NUMBERS),   # exclude admins
            )
            .order_by(Client.name.asc())
            .all()
        )

        log.info("[client-weekly] clients_with_wa=%s window=%s..%s", len(clients), start, end)

        for c in clients:
            bookings: List[Tuple[date, time]] = (
                s.query(Session.session_date, Session.start_time)
                .join(Booking, Booking.session_id == Session.id)
                .filter(
                    Booking.client_id == c.id,
                    Booking.status == "confirmed",
                    Session.session_date >= start,
                    Session.session_date <= end,
                )
                .order_by(Session.session_date.asc(), Session.start_time.asc())
                .all()
            )

            if bookings:
                items_list = [_fmt_item(d, t) for d, t in bookings]
                items_str = " • ".join(items_list)
            else:
                items_str = "No sessions booked this week — we miss you at the studio! Reply BOOK to grab a spot."

            items_str = _clean_one_line(items_str)
            name_str = _clean_one_line(c.name or "there")

            ok = _send_template_with_fallback(
                to=c.wa_number,
                template="client_weekly_schedule_us",
                variables={"1": name_str, "2": items_str},
                preferred_lang=TEMPLATE_LANG,
            )
            sent += 1 if ok else 0

    log.info("[client-weekly] sent=%s window=%s days", sent, window_days)
    return sent
