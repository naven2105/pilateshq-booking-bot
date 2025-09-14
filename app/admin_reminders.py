# app/admin_reminders.py
"""
Admin Reminders (template-based, aligned to your approved templates)
--------------------------------------------------------------------
Uses:
- admin_hourly_update ({{1}} time, {{2}} confirmed count)
- admin_20h00        ({{1}} total sessions today, {{2}} details list)

Notes:
- Sends via templates so it works outside WhatsApp's 24h window.
- If there are no matching sessions, sensible defaults are used.
"""

from __future__ import annotations
import logging
from datetime import date, datetime, timedelta
from typing import List, Tuple

from sqlalchemy import and_, cast, String, func

from .db import db_session
from .models import Client, Booking, Session
from . import utils, config

log = logging.getLogger(__name__)

# Template names / languages (match what you showed in WhatsApp Manager)
T_ADMIN_HOURLY = getattr(config, "ADMIN_TEMPLATE_HOURLY", "admin_hourly_update")
T_ADMIN_DAILY  = getattr(config, "ADMIN_TEMPLATE_DAILY",  "admin_20h00")
LANG_ADMIN     = getattr(config, "ADMIN_TEMPLATE_LANG",   "en_ZA")  # your admin templates are English (ZAF)


def _time_hhmm(dt_obj) -> str:
    try:
        return dt_obj.strftime("%H:%M")
    except Exception:
        return str(dt_obj)


def run_admin_hourly() -> None:
    """
    Hourly digest:
      {{1}} → next hour slot time (e.g., 09:00) or 'None'
      {{2}} → confirmed booking count for that time (sum across sessions)
    """
    now = datetime.now()
    target = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    today = date.today()

    # Count confirmed bookings for sessions starting at the next top-of-hour
    q = (
        db_session.query(func.count(Booking.client_id))
        .join(Session, Booking.session_id == Session.id)
        .filter(
            and_(
                Session.session_date == today,
                Session.start_time == target.time(),
                cast(Booking.status, String) == "confirmed",
            )
        )
    )

    confirmed_count = int(q.scalar() or 0)
    time_label = _time_hhmm(target)

    # Broadcast to all admins via template
    for admin_wa in (config.ADMIN_NUMBERS or []):
        utils.send_whatsapp_template(
            to=admin_wa,
            template_name=T_ADMIN_HOURLY,
            lang_code=LANG_ADMIN,
            body_params=[time_label, str(confirmed_count)],
        )
    log.info("[admin-hourly] time=%s confirmed=%s admins=%s", time_label, confirmed_count, len(config.ADMIN_NUMBERS))


def run_admin_daily() -> None:
    """
    Daily 20h00 recap:
      {{1}} → total sessions today
      {{2}} → details list, e.g. "- 06:00 (2)\n- 09:00 (3)"
    """
    today = date.today()

    # For each session today, compute confirmed count
    rows: List[Tuple[object, int]] = (
        db_session.query(
            Session.start_time,
            func.count(Booking.client_id).filter(cast(Booking.status, String) == "confirmed"),
        )
        .outerjoin(Booking, Booking.session_id == Session.id)
        .filter(Session.session_date == today)
        .group_by(Session.start_time)
        .order_by(Session.start_time)
        .all()
    )

    total_sessions = len(rows)
    if rows:
        details_lines = [f"- {_time_hhmm(st)} ({cnt})" for st, cnt in rows]
        details = "\n".join(details_lines)
    else:
        details = "No sessions scheduled."

    for admin_wa in (config.ADMIN_NUMBERS or []):
        utils.send_whatsapp_template(
            to=admin_wa,
            template_name=T_ADMIN_DAILY,
            lang_code=LANG_ADMIN,
            body_params=[str(total_sessions), details],
        )
    log.info("[admin-daily] total_sessions=%s admins=%s", total_sessions, len(config.ADMIN_NUMBERS))
