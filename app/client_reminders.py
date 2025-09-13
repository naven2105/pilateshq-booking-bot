# app/client_reminders.py
"""
Client Reminders
----------------
Automated outbound messages to clients:
- Night-before (20h00) reminders
- 1-hour before session reminders
- Weekly schedule preview (Sunday 18h00)

Returns an integer "sent" count to the caller.
"""

import logging
from datetime import date, datetime, timedelta

from sqlalchemy import and_, func

from .db import db_session
from .models import Client, Booking, Session
from . import utils

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _send_safe(wa_number: str | None, text: str) -> bool:
    """Send a WhatsApp text if we have a valid number."""
    if not wa_number:
        return False
    try:
        utils.send_whatsapp_text(wa_number, text)
        return True
    except Exception:
        log.exception("Failed to send WhatsApp to %s", wa_number)
        return False


def _fmt_dt(d: date, t) -> tuple[str, str]:
    """Format (date, time) as strings."""
    try:
        d_str = d.strftime("%Y-%m-%d")
    except Exception:
        d_str = str(d)
    try:
        t_str = t.strftime("%H:%M")
    except Exception:
        t_str = str(t)
    return d_str, t_str


# ──────────────────────────────────────────────────────────────────────────────
# Night-before reminders (run around 20:00)
# ──────────────────────────────────────────────────────────────────────────────

def run_client_tomorrow() -> int:
    """
    Send a reminder for sessions happening tomorrow to each booked client.
    Returns number of messages attempted (successfully sent).
    """
    tomorrow = date.today() + timedelta(days=1)

    rows = (
        db_session.query(Client.wa_number, Session.session_date, Session.start_time)
        .join(Booking, Booking.client_id == Client.id)
        .join(Session, Booking.session_id == Session.id)
        .filter(
            Booking.status == "confirmed",
            Session.session_date == tomorrow,
            Client.wa_number.isnot(None),
        )
        .order_by(Session.start_time)
        .all()
    )

    sent = 0
    for wa, sdate, stime in rows:
        d_str, t_str = _fmt_dt(sdate, stime)
        text = f"📅 Reminder: Your Pilates session is *tomorrow* ({d_str}) at *{t_str}*. Reply 'cancel' if you can’t make it."
        sent += 1 if _send_safe(wa, text) else 0

    log.info("[reminders:tomorrow] rows=%s sent=%s", len(rows), sent)
    return sent


# ──────────────────────────────────────────────────────────────────────────────
# 1-hour reminders (run hourly)
# ──────────────────────────────────────────────────────────────────────────────

def run_client_next_hour() -> int:
    """
    Send a reminder for sessions starting at the next top-of-the-hour.
    Example: If it's 08:15 now, target sessions at 09:00 today.
    """
    now = datetime.now()
    target = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    next_time = target.time()
    today = date.today()

    rows = (
        db_session.query(Client.wa_number, Session.session_date, Session.start_time)
        .join(Booking, Booking.client_id == Client.id)
        .join(Session, Booking.session_id == Session.id)
        .filter(
            Booking.status == "confirmed",
            Session.session_date == today,
            Session.start_time == next_time,
            Client.wa_number.isnot(None),
        )
        .order_by(Session.start_time)
        .all()
    )

    sent = 0
    for wa, sdate, stime in rows:
        d_str, t_str = _fmt_dt(sdate, stime)
        text = f"⏰ Starting soon: Your Pilates session is at *{t_str}* today ({d_str}). See you shortly!"
        sent += 1 if _send_safe(wa, text) else 0

    log.info("[reminders:next-hour] time=%s rows=%s sent=%s", next_time, len(rows), sent)
    return sent


# ──────────────────────────────────────────────────────────────────────────────
# Weekly preview (run Sunday 18:00)
# ──────────────────────────────────────────────────────────────────────────────

def run_client_weekly() -> int:
    """
    Send each client their upcoming sessions for the next 7 days.
    One message per client, listing all booked sessions in the window.
    """
    start = date.today()
    end = start + timedelta(days=7)

    # Pull all client bookings in the next 7 days
    rows = (
        db_session.query(Client.wa_number, Session.session_date, Session.start_time)
        .join(Booking, Booking.client_id == Client.id)
        .join(Session, Booking.session_id == Session.id)
        .filter(
            Booking.status == "confirmed",
            Session.session_date.between(start, end),
            Client.wa_number.isnot(None),
        )
        .order_by(Client.wa_number, Session.session_date, Session.start_time)
        .all()
    )

    # Group by client WhatsApp number
    by_client: dict[str, list[tuple[date, object]]] = {}
    for wa, sdate, stime in rows:
        by_client.setdefault(wa, []).append((sdate, stime))

    sent = 0
    for wa, items in by_client.items():
        lines = []
        for sdate, stime in items:
            d_str, t_str = _fmt_dt(sdate, stime)
            lines.append(f"- {d_str} at {t_str}")
        text = "📆 Your Pilates sessions this week:\n" + "\n".join(lines)
        sent += 1 if _send_safe(wa, text) else 0

    log.info("[reminders:weekly] clients=%s sent=%s", len(by_client), sent)
    return sent
