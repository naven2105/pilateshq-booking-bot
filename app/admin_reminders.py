# app/admin_reminders.py
from __future__ import annotations

import logging
from datetime import datetime, timedelta, time, date

from sqlalchemy import text
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

def _try_reserve_send(s: OrmSession, wa: str, template: str, d: date, t: time) -> bool:
    """
    Attempt to insert a unique send key in reminders_sendlog.
    Returns True if this process reserved the send (i.e., not previously sent).
    """
    res = s.execute(
        text(
            """
            INSERT INTO reminders_sendlog (wa_number, template, session_date, start_time)
            VALUES (:wa, :tpl, :d, :t)
            ON CONFLICT (wa_number, template, session_date, start_time)
            DO NOTHING
            """
        ),
        {"wa": wa, "tpl": template, "d": d, "t": t},
    )
    s.commit()
    return res.rowcount == 1

# ──────────────────────────────────────────────────────────────────────────────
# Public jobs
# ──────────────────────────────────────────────────────────────────────────────

def run_admin_tick() -> None:
    """
    Hourly small pulse for admins:
      - Next top-of-hour time string
      - Current confirmed count for the next hour
    Dedupe key: (today, next_hour_time).
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

        for admin in ADMIN_NUMBERS:
            if not _try_reserve_send(s, admin, "admin_hourly_update", today, next_hour):
                log.info("[admin-hourly][skip-duplicate] to=%s time=%s", admin, next_str)
                continue
            ok, status, resp = utils.send_template(
                to=admin,
                template="admin_hourly_update",
                lang=TEMPLATE_LANG or "en",
                variables={"1": next_str, "2": str(count)},
            )
            log.info("[admin-hourly][send] to=%s status=%s ok=%s count=%d", admin, status, ok, count)


def run_admin_daily() -> None:
    """
    20:00 daily summary for admins.
    Always sends (with 'No sessions today.' when empty).
    Dedupe key: (today, 20:00).
    """
    today = datetime.now().date()
    sentinel_time = time(20, 0)

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
        details = "No sessions today." if today_count == 0 else " | ".join(
            _fmt_admin_line(d, t, n) for d, t, n in rows
        )

        for admin in ADMIN_NUMBERS:
            if not _try_reserve_send(s, admin, "admin_20h00", today, sentinel_time):
                log.info("[admin-daily][skip-duplicate] to=%s date=%s", admin, today.isoformat())
                continue
            ok, status, resp = utils.send_template(
                to=admin,
                template="admin_20h00",
                lang=TEMPLATE_LANG or "en",
                variables={"1": str(today_count), "2": details},
            )
            if not ok:
                # Fallback to text to ensure visibility.
                msg = f"Number of upcoming sessions: {today_count} total. Here are the details of today’s schedule: {details} End of message."
                utils.send_whatsapp_text(admin, msg)
            log.info("[admin-daily][send] to=%s status=%s ok=%s count=%d", admin, status, ok, today_count)
