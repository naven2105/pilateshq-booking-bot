# app/client_reminders.py
from __future__ import annotations

import logging
from datetime import datetime, timedelta, time, date

from sqlalchemy import and_, func
from sqlalchemy.orm import Session as OrmSession

from .db import db_session
from .config import TEMPLATE_LANG
from . import utils
from .models import Client, Session, Booking

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _fmt_week_item(d: date, t: time) -> str:
    # Single-line, template-safe (no \n / \t). Example: "Mon 16 Sep 09:00"
    return f"{d.strftime('%a %d %b')} {t.strftime('%H:%M')}"

def _send_weekly_template_or_text(to_wa: str, name: str, items_list: list[str]) -> bool:
    """
    Use WhatsApp template 'weekly_template_message' with vars:
      name -> client's display name
      items -> single-line list, ' • ' separated OR 'No sessions booked this week.'
    Fall back to plain text if template call fails for any reason.
    """
    items_str = " • ".join(items_list) if items_list else "No sessions booked this week."
    # Guard: WhatsApp rejects >4 consecutive spaces / newlines; keep it tight.
    items_str = " ".join(items_str.split())

    try:
        ok, status, resp = utils.send_template(
            to=to_wa,
            template="weekly_template_message",
            lang=TEMPLATE_LANG or "en",
            variables={"name": name, "items": items_str},
        )
        if not ok:
            log.error("[weekly][tpl-fail] to=%s status=%s resp=%s", to_wa, status, resp)
            # Fall back to text
            msg = f"Hi {name}, here’s your PilatesHQ schedule for the week: {items_str}. Looking forward to seeing you!"
            utils.send_whatsapp_text(to_wa, msg)
            return False
        return True
    except Exception:
        log.exception("[weekly][tpl-exc] to=%s", to_wa)
        msg = f"Hi {name}, here’s your PilatesHQ schedule for the week: {items_str}. Looking forward to seeing you!"
        utils.send_whatsapp_text(to_wa, msg)
        return False

def _send_tomorrow_template_or_text(to_wa: str, when_str: str) -> bool:
    try:
        ok, status, resp = utils.send_template(
            to=to_wa,
            template="session_tomorrow",
            lang=TEMPLATE_LANG or "en",
            variables={"1": when_str} if isinstance(when_str, str) else {"time": when_str},
        )
        if not ok:
            log.error("[tomorrow][tpl-fail] to=%s status=%s resp=%s", to_wa, status, resp)
            utils.send_whatsapp_text(to_wa, f"📅 Reminder: Your Pilates session is tomorrow at {when_str}. See you there 🤸‍♀️")
            return False
        return True
    except Exception:
        log.exception("[tomorrow][tpl-exc] to=%s", to_wa)
        utils.send_whatsapp_text(to_wa, f"📅 Reminder: Your Pilates session is tomorrow at {when_str}. See you there 🤸‍♀️")
        return False

def _send_next_hour_template_or_text(to_wa: str, when_str: str) -> bool:
    try:
        ok, status, resp = utils.send_template(
            to=to_wa,
            template="session_next_hour",
            lang=TEMPLATE_LANG or "en",
            variables={"1": when_str} if isinstance(when_str, str) else {"time": when_str},
        )
        if not ok:
            log.error("[next-hour][tpl-fail] to=%s status=%s resp=%s", to_wa, status, resp)
            utils.send_whatsapp_text(to_wa, f"⏰ Reminder: Your Pilates session starts at {when_str} today. Reply CANCEL if you cannot attend.")
            return False
        return True
    except Exception:
        log.exception("[next-hour][tpl-exc] to=%s", to_wa)
        utils.send_whatsapp_text(to_wa, f"⏰ Reminder: Your Pilates session starts at {when_str} today. Reply CANCEL if you cannot attend.")
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Public jobs (called by /tasks/run-reminders)
# ──────────────────────────────────────────────────────────────────────────────

def run_client_weekly(window_days: int = 7) -> int:
    """
    NEW BEHAVIOUR: Send a weekly preview to *all clients with a WhatsApp number*.
    - If client has 0 confirmed bookings in the window → send 'No sessions booked this week.'
    - Uses template 'weekly_template_message' (falls back to text).
    Returns: number of WhatsApps attempted (sent count).
    """
    sent = 0
    today = datetime.now().date()
    end_date = today + timedelta(days=max(1, window_days) - 1)

    with db_session() as s:  # type: OrmSession
        # 1) Get every client with a WA number
        clients = (
            s.query(Client.id, Client.name, Client.wa_number)
            .filter(Client.wa_number.isnot(None))
            .all()
        )

        if not clients:
            log.info("[weekly] no clients with wa_number")
            return 0

        # 2) Map confirmed bookings in the next 7 days per client
        rows = (
            s.query(
                Booking.client_id,
                Session.session_date,
                Session.start_time,
            )
            .join(Session, Session.id == Booking.session_id)
            .filter(
                Booking.status == "confirmed",
                Session.session_date >= today,
                Session.session_date <= end_date,
            )
            .all()
        )

        per_client: dict[int, list[str]] = {}
        for client_id, d, t in rows:
            per_client.setdefault(client_id, []).append(_fmt_week_item(d, t))

        # 3) Send per client; include “no sessions” branch
        for cid, name, wa in clients:
            items = sorted(per_client.get(cid, []))
            ok = _send_weekly_template_or_text(wa, name or "there", items)
            sent += 1
            log.info("[weekly][send] to=%s items=%d ok=%s", wa, len(items), ok)

    return sent


def run_client_tomorrow() -> int:
    """
    Send 'tomorrow' reminders to all confirmed bookings for tomorrow.
    Uses template 'session_tomorrow' (falls back to text).
    """
    sent = 0
    tomorrow = datetime.now().date() + timedelta(days=1)

    with db_session() as s:  # type: OrmSession
        rows = (
            s.query(
                Client.wa_number,
                Session.start_time,
                Client.name,
            )
            .join(Booking, Booking.client_id == Client.id)
            .join(Session, Session.id == Booking.session_id)
            .filter(
                Client.wa_number.isnot(None),
                Booking.status == "confirmed",
                Session.session_date == tomorrow,
            )
            .order_by(Session.start_time.asc())
            .all()
        )

        for wa, start_t, name in rows:
            when_str = start_t.strftime("%H:%M")
            ok = _send_tomorrow_template_or_text(wa, when_str)
            sent += 1
            log.info("[tomorrow][send] to=%s time=%s ok=%s", wa, when_str, ok)

    return sent


def run_client_next_hour() -> int:
    """
    Send 'next hour' reminders to all confirmed bookings where the start_time falls within [now, now+60m].
    Uses template 'session_next_hour' (falls back to text).
    """
    sent = 0
    now = datetime.now()
    today = now.date()
    next_hour_dt = now + timedelta(hours=1)
    hour_window_end = next_hour_dt.time()

    with db_session() as s:  # type: OrmSession
        # We only look at today's sessions between now.time() and +60m
        rows = (
            s.query(
                Client.wa_number,
                Session.start_time,
                Client.name,
            )
            .join(Booking, Booking.client_id == Client.id)
            .join(Session, Session.id == Booking.session_id)
            .filter(
                Client.wa_number.isnot(None),
                Booking.status == "confirmed",
                Session.session_date == today,
                Session.start_time >= now.time(),
                Session.start_time <= hour_window_end,
            )
            .order_by(Session.start_time.asc())
            .all()
        )

        for wa, start_t, name in rows:
            when_str = start_t.strftime("%H:%M")
            ok = _send_next_hour_template_or_text(wa, when_str)
            sent += 1
            log.info("[next-hour][send] to=%s time=%s ok=%s", wa, when_str, ok)

    return sent
