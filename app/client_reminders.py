# app/client_reminders.py
from __future__ import annotations

import logging
from datetime import datetime, date, time, timedelta
from typing import List, Tuple

from sqlalchemy.orm import Session as OrmSession

from .db import get_session

from .models import Client, Session, Booking
from . import utils

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _fmt_hhmm(t: time) -> str:
    return t.strftime("%H:%M")

def _fmt_item(d: date, t: time) -> str:
    return f"{d.strftime('%a %d %b')} {t.strftime('%H:%M')}"

def _clean_one_line(s: str) -> str:
    return " ".join((s or "").split())

# ─────────────────────────────────────────────
# Tomorrow reminders — template: client_session_tomorrow_us
# ─────────────────────────────────────────────

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
            )
            .order_by(Session.start_time.asc())
            .all()
        )
        for wa, tt in rows:
            ok, status, _ = utils.send_whatsapp_template(
                wa,
                "client_session_tomorrow_us",
                "en_US",   # ✅ only US
                [_fmt_hhmm(tt)],
            )
            log.info("[client-tomorrow] to=%s status=%s ok=%s", wa, status, ok)
            sent += 1 if ok else 0
    log.info("[client-tomorrow] sent=%s", sent)
    return sent

# ─────────────────────────────────────────────
# Next-hour reminders — template: client_session_next_hour_us
# ─────────────────────────────────────────────

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
            )
            .order_by(Session.start_time.asc())
            .all()
        )
        for wa, tt in rows:
            ok, status, _ = utils.send_whatsapp_template(
                wa,
                "client_session_next_hour_us",
                "en_US",
                [_fmt_hhmm(tt)],
            )
            log.info("[client-next-hour] to=%s status=%s ok=%s", wa, status, ok)
            sent += 1 if ok else 0
    log.info("[client-next-hour] sent=%s", sent)
    return sent

# ─────────────────────────────────────────────
# Weekly preview — template: client_weekly_schedule_us
# ─────────────────────────────────────────────

def run_client_weekly(window_days: int = 7) -> int:
    start = date.today()
    end = start + timedelta(days=max(1, window_days) - 1)
    sent = 0

    with db_session() as s:  # type: OrmSession
        clients: List[Client] = (
            s.query(Client)
            .filter(Client.wa_number.isnot(None))
            .order_by(Client.name.asc())
            .all()
        )

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
                items_str = "No sessions booked this week — we miss you! Reply BOOK to grab a spot."

            items_str = _clean_one_line(items_str)
            name_str = _clean_one_line(c.name or "there")

            ok, status, _ = utils.send_whatsapp_template(
                c.wa_number,
                "client_weekly_schedule_us",
                "en_US",
                [name_str, items_str],
            )
            log.info("[client-weekly] to=%s status=%s ok=%s", c.wa_number, status, ok)
            sent += 1 if ok else 0

    log.info("[client-weekly] sent=%s", sent)
    return sent
