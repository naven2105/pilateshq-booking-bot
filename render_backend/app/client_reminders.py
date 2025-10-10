"""
client_reminders.py
────────────────────────────────────────────
Integrated client reminder service for PilatesHQ.

Connects Google Apps Script → Render backend.
Handles:
 • Night-before reminders (tomorrow’s sessions)
 • 1-hour reminders
 • Weekly previews (Sunday 20h00)

Uses SQLAlchemy ORM and WhatsApp templates via utils.send_whatsapp_template().
"""

from __future__ import annotations
import logging
from datetime import datetime, date, time, timedelta
from typing import List, Tuple
from flask import Blueprint, request, jsonify
from sqlalchemy.orm import Session as OrmSession

from .db import get_session
from .models import Client, Session, Booking
from . import utils
from .config import TEMPLATE_LANG
from .utils import sanitize_param, safe_execute

bp = Blueprint("client_reminders", __name__)
log = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _fmt_hhmm(t: time) -> str:
    return t.strftime("%H:%M")

def _fmt_item(d: date, t: time) -> str:
    return f"{d.strftime('%a %d %b')} {t.strftime('%H:%M')}"

def _lang_candidates(preferred: str | None) -> List[str]:
    cand = [x for x in [preferred, "en", "en_US"] if x]
    seen, out = set(), []
    for c in cand:
        if c not in seen:
            out.append(c)
            seen.add(c)
    return out

def _send_template_with_fallback(to: str, template: str, variables: dict, preferred_lang: str | None) -> bool:
    """Try multiple language fallbacks for a WhatsApp template."""
    for lang in _lang_candidates(preferred_lang):
        try:
            resp = utils.send_whatsapp_template(
                to=to,
                name=template,
                lang=lang,
                variables=[sanitize_param(v) for v in variables.values()],
            )
            ok = resp.get("ok", False)
            status = resp.get("status_code")
            log.info("[tpl-send] to=%s tpl=%s lang=%s status=%s ok=%s", to, template, lang, status, ok)
            if ok:
                return True
        except Exception as e:
            log.warning("[tpl-send] exception for %s: %s", to, e)
    return False


# ──────────────────────────────────────────────
# Core reminder jobs
# ──────────────────────────────────────────────

def run_client_tomorrow() -> int:
    """Send reminders for tomorrow’s confirmed sessions."""
    log.info("→ using template=client_session_tomorrow_us")
    tomorrow = date.today() + timedelta(days=1)
    sent = 0
    with get_session() as s:  # type: OrmSession
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
            try:
                ok = _send_template_with_fallback(
                    to=wa,
                    template="client_session_tomorrow_us",
                    variables={"1": _fmt_hhmm(tt)},
                    preferred_lang=TEMPLATE_LANG,
                )
                sent += 1 if ok else 0
            except Exception as e:
                log.warning("[client-tomorrow] failed for %s: %s", wa, e)

    log.info("[client-tomorrow] date=%s candidates=%s sent=%s",
             tomorrow.isoformat(), len(rows), sent)
    return sent


def run_client_next_hour() -> int:
    """Send reminders for sessions starting within the next hour."""
    log.info("→ using template=client_session_next_hour_us")
    now = datetime.now()
    today = now.date()
    in_one_hour = (now + timedelta(hours=1)).time()
    start_t = now.time()
    end_t = in_one_hour
    sent = 0

    with get_session() as s:
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
            try:
                ok = _send_template_with_fallback(
                    to=wa,
                    template="client_session_next_hour_us",
                    variables={"1": _fmt_hhmm(tt)},
                    preferred_lang=TEMPLATE_LANG,
                )
                sent += 1 if ok else 0
            except Exception as e:
                log.warning("[client-next-hour] failed for %s: %s", wa, e)

    log.info("[client-next-hour] window=%s-%s candidates=%s sent=%s",
             start_t, end_t, len(rows), sent)
    return sent


def run_client_weekly(window_days: int = 7) -> int:
    """Send a weekly preview schedule to all active clients."""
    log.info("→ using template=client_weekly_schedule_us")
    start = date.today()
    end = start + timedelta(days=max(1, window_days) - 1)
    sent = 0

    with get_session() as s:  # type: OrmSession
        clients: List[Client] = (
            s.query(Client)
            .filter(Client.wa_number.isnot(None))
            .order_by(Client.name.asc())
            .all()
        )

        log.info("[client-weekly] clients_with_wa=%s window=%s..%s",
                 len(clients), start, end)

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
                items_str = "\n• " + "\n• ".join(items_list)
            else:
                items_str = (
                    "No sessions booked this week — "
                    "we miss you at the studio! Reply BOOK to grab a spot."
                )

            try:
                ok = _send_template_with_fallback(
                    to=c.wa_number,
                    template="client_weekly_schedule_us",
                    variables={"1": c.name or "there", "2": items_str},
                    preferred_lang=TEMPLATE_LANG,
                )
                sent += 1 if ok else 0
            except Exception as e:
                log.warning("[client-weekly] failed for %s: %s", c.wa_number, e)

    log.info("[client-weekly] sent=%s window=%s days", sent, window_days)
    return sent


# ──────────────────────────────────────────────
# Flask endpoints (Apps Script → Render)
# ──────────────────────────────────────────────

@bp.route("/client-reminders", methods=["POST"])
@safe_execute
def handle_client_reminders():
    """Entry point for Google Apps Script jobs."""
    payload = request.get_json(force=True)
    job_type = (payload.get("type") or "").strip()
    log.info(f"[client-reminders] received type={job_type}")

    if job_type == "client-night-before":
        sent = run_client_tomorrow()
    elif job_type == "client-week-ahead":
        sent = run_client_weekly()
    elif job_type == "client-next-hour":
        sent = run_client_next_hour()
    else:
        return jsonify({"ok": False, "error": f"Unknown job type: {job_type}"}), 400

    return jsonify({"ok": True, "sent": sent})


@bp.route("/client-reminders/test", methods=["GET"])
def test_route():
    """Simple health check."""
    log.info("[client-reminders] test route hit")
    return jsonify({"ok": True, "msg": "client_reminders route active"})
