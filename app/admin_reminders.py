# admin_reminders.py
"""
Admin Reminders
---------------
Handles automated notifications for admin:
- Hourly updates
- Daily prep (morning)
- Daily recap (20h00)
"""

import logging
from datetime import datetime, date
from . import crud, utils

log = logging.getLogger(__name__)


def run_admin_hourly():
    """Send hourly update with upcoming sessions."""
    sessions = crud.get_weekly_schedule()  # or a narrower window
    if not sessions:
        msg = "⏰ No more sessions scheduled for this hour."
    else:
        lines = [f"- {s['date']} {s['time']} ({s['status']})" for s in sessions]
        msg = "⏰ Hourly Update:\n" + "\n".join(lines)

    utils.send_whatsapp_text(utils.ADMIN_NUMBER, msg)


def run_admin_morning():
    """Send full-day prep view at 06h00."""
    today = date.today()
    sessions = crud.get_weekly_schedule()  # could be filtered to today
    if not sessions:
        msg = "📅 No sessions scheduled for today."
    else:
        lines = [f"- {s['date']} {s['time']} ({s['status']})" for s in sessions]
        msg = "📅 Today’s Sessions:\n" + "\n".join(lines)

    utils.send_whatsapp_text(utils.ADMIN_NUMBER, msg)


def run_admin_daily():
    """Send 20h00 recap to admin with counts + details."""
    today = date.today()
    count = crud.get_clients_today()
    cancellations = crud.get_cancellations_today()

    send_admin_daily(utils.ADMIN_NUMBER, count, cancellations)


def send_admin_daily(admin_number: str, count: int, details: list):
    """
    Format and send the admin daily recap.
    Args:
        admin_number: WhatsApp number of admin
        count: number of clients today
        details: list of cancellations (dicts)
    """
    if not count and not details:
        msg = "📊 Daily Recap: No clients today."
    else:
        msg = f"📊 Daily Recap:\nTotal clients today: *{count}*"
        if details:
            lines = [f"- {c['client']} ({c['date']} {c['time']})" for c in details]
            msg += "\n❌ Cancellations:\n" + "\n".join(lines)

    utils.send_whatsapp_text(admin_number, msg)
