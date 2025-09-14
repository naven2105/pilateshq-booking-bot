# app/admin_reminders.py
from __future__ import annotations

import logging
from datetime import datetime, timedelta, time, date

from sqlalchemy.orm import Session as OrmSession

from .db import db_session
from .config import ADMIN_NUMBERS, TEMPLATE_LANG
from . import utils
from .models import Client, Session, Booking

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _fmt_admin_line(d: date, t: time, client_name: str) -> str:
    # Compact, one-line per booking (kept as text for admin template body).
    return f"{d.strftime('%a %d %b')} {t.strftime('%H:%M')} — {client_name}"

def _send_admin_hourly(next_time_str: str, confirmed_count: int) -> None:
    for admin in ADMIN_NUMBERS:
        ok, status, resp = utils.send_template(
            to=admin,
            template="admin_hourly_update",
            lang=TEMPLATE_LANG or "en",
            variables={"1": next_time_str, "2": str(confirmed_count)},
        )
        log.info("[admin-hourly][send] to=%s tpl=admin_hourly_update lang=%s status=%s ok=%s",
                 admin, TEMPLATE_LANG or "en", status, ok)

def _send_admin_daily_summary(today_count: int, details_text: str) -> None:
    for admin in ADMIN_NUMBERS:
        ok, status, resp = utils.send_template(
            to=admin,
            template="admin_20h00",
            lang=TEMPLATE_LANG or "en",
            variables={"1": str(today_count), "2": details_text or "No sessions today."},
        )
        if not ok:
            # Fallback to text to ensure visibility.
            msg = f"Number of upcoming sessions: {today_count} total. Here are the details of today’s schedule: {details_text or 'No sessions today.'} End of message."
            utils.send_whatsapp_text(admin, msg)
        log.info("[admin-daily][send] to=%s status=%s ok=%s", admin, status, ok)

# ──────────────────────────────────────────────────────────────────────────────
# Public jobs
# ──────────────────────────────────────────────────────────────────────────────

def run_admin_tick() -> None:
    """
    Hourly small pulse for admins:
      - Next top-of-hour time string
      - Current confirmed count for the next hour
    """
    now = datetime.now()
    next_hour = (now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)).time()
    next_str = next_hour.strftime("%H:%M")
    today = now.date()

    with db_session() as s:  # type: OrmSession
        count = (
            s.query(Booking)
            .join(Session, Session.id == Booking.session_id)
            .filter(
                Booking.status == "confirmed",
                Session.session_date == today,
                Session.start_time >= now.time(),
                Session.start_time < (now + timedelta(hours=1)).time(),
            )
            .count()
        )

    _send_admin_hourly(next_str, count)
    log.info("[admin-hourly] time=%s confirmed=%d admins=%d", next_str, count, len(ADMIN_NUMBERS))


def run_admin_daily() -> None:
    """
    20:00 daily summary for admins.
    Always sends; when there are no sessions, 'details' clearly says so.
    """
    today = datetime.now().date()

    with db_session() as s:  # type: OrmSession
        rows = (
            s.query(Session.session_date, Session.start_time, Client.name)
            .join(Booking, Booking.session_id == Session.id)
            .join(Client, Client.id == Booking.client_id)
            .filter(
                Booking.status == "confirmed",
                Session.session_date == today,
            )
            .order_by(Session.start_time.asc())
            .all()
        )

    today_count = len(rows)
    if today_count == 0:
        details = "No sessions today."
    else:
        details = " | ".join(_fmt_admin_line(d, t, n) for d, t, n in rows)

    _send_admin_daily_summary(today_count, details)
    log.info("[admin-daily] count=%d", today_count)
