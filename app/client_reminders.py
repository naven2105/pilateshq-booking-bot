# app/client_reminders.py
"""
Client Reminders (Template-based)
---------------------------------
Automated outbound messages to clients:
- Night-before (20h00)
- 1-hour before
- Weekly preview (Sunday 18h00)

All sends use WhatsApp templates (HSM) so they deliver outside 24h.
Also fixes Postgres ENUM comparisons by casting the column to String.
"""

import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Tuple

from sqlalchemy import and_, cast, String

from .db import db_session
from .models import Client, Booking, Session
from . import utils, config

log = logging.getLogger(__name__)

# Template names (configurable via env-backed config.py if preferred)
T_CLIENT_TOMORROW = getattr(config, "CLIENT_TEMPLATE_TOMORROW", "session_tomorrow")
T_CLIENT_NEXT_HOUR = getattr(config, "CLIENT_TEMPLATE_NEXT_HOUR", "session_next_hour")
T_CLIENT_WEEKLY = getattr(config, "CLIENT_TEMPLATE_WEEKLY", "client_weekly")
LANG = getattr(config, "TEMPLATE_LANG", "en")


def _fmt_dt(d: date, t) -> Tuple[str, str]:
    try:
        d_str = d.strftime("%Y-%m-%d")
    except Exception:
        d_str = str(d)
    try:
        t_str = t.strftime("%H:%M")
    except Exception:
        t_str = str(t)
    return d_str, t_str


def _send_client_template(wa_number: str, template_name: str, text_body: str) -> bool:
    if not wa_number:
        return False
    try:
        res = utils.send_whatsapp_template(
            to=wa_number,
            template_name=template_name,
            lang_code=LANG,
            body_params=[text_body],
        )
        code = res.get("status_code", 0)
        if code >= 400 or code == 0:
            log.error(
                "Client template send failed wa=%s tpl=%s code=%s resp=%s",
                wa_number, template_name, code, res.get("response"),
            )
            return False
        return True
    except Exception:
        log.exception("Failed to send client template wa=%s tpl=%s", wa_number, template_name)
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Night-before reminders (run around 20:00)
# ──────────────────────────────────────────────────────────────────────────────
def run_client_tomorrow() -> int:
    """Send a reminder for sessions happening tomorrow; returns successful sends."""
    tomorrow = date.today() + timedelta(days=1)
    try:
        rows: List[Tuple[str, date, object]] = (
            db_session.query(Client.wa_number, Session.session_date, Session.start_time)
            .join(Booking, Booking.client_id == Client.id)
            .join(Session, Booking.session_id == Session.id)
            .filter(
                and_(
                    cast(Booking.status, String) == "confirmed",  # cast ENUM->text
                    Session.session_date == tomorrow,
                    Client.wa_number.isnot(None),
                )
            )
            .order_by(Session.start_time)
            .all()
        )

        sent = 0
        for wa, sdate, stime in rows:
            d_str, t_str = _fmt_dt(sdate, stime)
            body = f"📅 Reminder: Your Pilates session is *tomorrow* ({d_str}) at *{t_str}*. Reply 'cancel' if you can’t make it."
            if _send_client_template(wa, T_CLIENT_TOMORROW, body):
                sent += 1

        log.info("[reminders:tomorrow] rows=%s sent=%s", len(rows), sent)
        return sent

    except Exception:
        log.exception("[reminders:tomorrow] query failed")
        db_session.rollback()
        raise


# ──────────────────────────────────────────────────────────────────────────────
# 1-hour reminders (run hourly)
# ──────────────────────────────────────────────────────────────────────────────
def run_client_next_hour() -> int:
    """Send a reminder for sessions starting at the next top-of-the-hour."""
    now = datetime.now()
    target = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    next_time = target.time()
    today = date.today()
    try:
        rows: List[Tuple[str, date, object]] = (
            db_session.query(Client.wa_number, Session.session_date, Session.start_time)
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
        for wa, sdate, stime in rows:
            d_str, t_str = _fmt_dt(sdate, stime)
            body = f"⏰ Starting soon: Your Pilates session is at *{t_str}* today ({d_str}). See you shortly!"
            if _send_client_template(wa, T_CLIENT_NEXT_HOUR, body):
                sent += 1

        log.info("[reminders:next-hour] time=%s rows=%s sent=%s", next_time, len(rows), sent)
        return sent

    except Exception:
        log.exception("[reminders:next-hour] query failed")
        db_session.rollback()
        raise


# ──────────────────────────────────────────────────────────────────────────────
# Weekly preview (run Sunday 18:00)
# ──────────────────────────────────────────────────────────────────────────────
def run_client_weekly() -> int:
    """Send each client their upcoming sessions for the next 7 days."""
    start = date.today()
    end = start + timedelta(days=7)
    try:
        rows: List[Tuple[str, date, object]] = (
            db_session.query(Client.wa_number, Session.session_date, Session.start_time)
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

        # Group by client
        by_client: Dict[str, List[Tuple[date, object]]] = {}
        for wa, sdate, stime in rows:
            by_client.setdefault(wa, []).append((sdate, stime))

        sent = 0
        for wa, items in by_client.items():
            lines = []
            for sdate, stime in items:
                d_str, t_str = _fmt_dt(sdate, stime)
                lines.append(f"- {d_str} at {t_str}")
            body = "📆 Your Pilates sessions this week:\n" + "\n".join(lines)
            if _send_client_template(wa, T_CLIENT_WEEKLY, body):
                sent += 1

        log.info("[reminders:weekly] clients=%s sent=%s", len(by_client), sent)
        return sent

    except Exception:
        log.exception("[reminders:weekly] query failed")
        db_session.rollback()
        raise
