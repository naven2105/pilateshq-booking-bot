# app/diag.py
from __future__ import annotations
import logging
from datetime import datetime, date, time, timedelta
from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, request
from sqlalchemy.orm import Session as OrmSession

from .db import db_session
from .models import Client, Session, Booking
from . import utils
from .config import TEMPLATE_LANG
from .tasks import LAST_RUN  # in-memory cron audit

diag_bp = Blueprint("diag", __name__)
log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Basic health
# ──────────────────────────────────────────────────────────────────────────────

@diag_bp.get("/")
def root():
    return "PilatesHQ bot is up.", 200

@diag_bp.get("/diag/db-test")
def db_test():
    try:
        with db_session() as s:
            s.execute("SELECT 1")
        return jsonify({"ok": True, "result": 1}), 200
    except Exception as e:
        log.exception("db-test failed")
        return jsonify({"ok": False, "error": str(e)}), 500

# ──────────────────────────────────────────────────────────────────────────────
# Cron / WA observability
# ──────────────────────────────────────────────────────────────────────────────

@diag_bp.get("/diag/cron-status")
def cron_status():
    """Expose last-run info and simple WA/API error counters (per process)."""
    return jsonify({
        "server_time": datetime.now().isoformat(timespec="seconds"),
        "timezone_hint": "Africa/Johannesburg (Render cron uses UTC)",
        "last_run": LAST_RUN,
        "error_counters": utils.get_error_counters(),
    }), 200

# ──────────────────────────────────────────────────────────────────────────────
# Template smoke tests
# ──────────────────────────────────────────────────────────────────────────────

@diag_bp.post("/diag/test-client-template")
def test_client_template():
    """
    Send 'session_tomorrow' template to a number for a given time.
    Example:
      POST /diag/test-client-template?to=2773...&time=09:00
    """
    to = request.args.get("to", "").strip()
    when = request.args.get("time", "09:00").strip()
    lang = TEMPLATE_LANG or "en"
    ok, status, resp = utils.send_template(
        to=to,
        template="session_tomorrow",
        lang=lang,
        variables={"1": when},
    )
    return jsonify({
        "ok": ok,
        "status_code": status,
        "response": resp,
        "to": to,
        "template": "session_tomorrow",
        "lang": lang,
    }), 200 if ok else 500

@diag_bp.post("/diag/test-weekly-template")
def test_weekly_template():
    """
    Send 'weekly_template_message' with name + items (semicolon separated).
    Example:
      POST /diag/test-weekly-template?to=2773...&name=Test&items=Mon%2016%20Sep%2009:00;Wed%2017%20Sep%2007:00
    """
    to = request.args.get("to", "").strip()
    name = request.args.get("name", "there").strip()
    items_raw = request.args.get("items", "").strip()
    items_list = [x.strip() for x in items_raw.split(";") if x.strip()]
    # One line; Meta rejects newlines / >4 spaces. Use bullet separator.
    items_str = " • ".join(items_list) if items_list else "No sessions booked this week."
    items_str = " ".join(items_str.split())
    lang = (TEMPLATE_LANG or "en").replace("_US", "")  # allow "en" or "en_ZA"

    ok, status, resp = utils.send_template(
        to=to,
        template="weekly_template_message",
        lang=lang,
        variables={"name": name, "items": items_str},
    )
    return jsonify({
        "ok": ok,
        "status_code": status,
        "response": resp,
        "to": to,
        "template": "weekly_template_message",
        "lang": lang,
        "vars": {"name": name, "items": items_str},
    }), 200 if ok else 500

# ──────────────────────────────────────────────────────────────────────────────
# Weekly dry-run (no sends) for a preview window
# ──────────────────────────────────────────────────────────────────────────────

@diag_bp.get("/diag/weekly-dry-run")
def weekly_dry_run():
    """
    Preview bookings that *would* be messaged in the next N days.
    Params:
      days=7
      status_in=confirmed (comma-separated if multiple)
      include_null_wa=0/1 (include clients without WhatsApp number)
    """
    try:
        days = int(request.args.get("days", "7"))
    except ValueError:
        days = 7
    status_in = [x.strip() for x in request.args.get("status_in", "confirmed").split(",") if x.strip()]
    include_null_wa = request.args.get("include_null_wa", "0") in ("1", "true", "True")

    start = date.today()
    end = start + timedelta(days=max(1, days) - 1)

    with db_session() as s:  # type: OrmSession
        q = (
            s.query(
                Client.id.label("client_id"),
                Client.name.label("client_name"),
                Client.wa_number.label("wa_number"),
                Session.session_date,
                Session.start_time,
                Booking.status.label("booking_status"),
            )
            .join(Booking, Booking.client_id == Client.id)
            .join(Session, Session.id == Booking.session_id)
            .filter(
                Booking.status.in_(status_in),
                Session.session_date >= start,
                Session.session_date <= end,
            )
            .order_by(Session.session_date.asc(), Session.start_time.asc())
        )
        rows = q.all()

    sample = []
    with_wa = 0
    without_wa = 0
    for r in rows:
        has_wa = bool(r.wa_number)
        with_wa += 1 if has_wa else 0
        without_wa += 0 if has_wa else 1
        would_send = has_wa or include_null_wa
        sample.append({
            "client_id": r.client_id,
            "client_name": r.client_name,
            "wa_number": r.wa_number,
            "session_date": r.session_date.isoformat(),
            "start_time": str(r.start_time),
            "booking_status": r.booking_status,
            "would_send": would_send,
        })
    return jsonify({
        "ok": True,
        "window_days": days,
        "status_in": status_in,
        "include_null_wa": include_null_wa,
        "total_matches": len(rows),
        "with_wa_number": with_wa,
        "without_wa_number": without_wa,
        "sample_first_100": sample[:100],
    }), 200

# ──────────────────────────────────────────────────────────────────────────────
# Demo seeding (creates client + two sessions + bookings)
# ──────────────────────────────────────────────────────────────────────────────

def _parse_hhmm(s: str) -> time:
    try:
        return datetime.strptime(s, "%H:%M").time()
    except Exception:
        return time(9, 0)

@diag_bp.post("/diag/seed-demo")
def seed_demo():
    """
    Create a demo client and two bookings on the next two days.
    Params:
      wa=27735534607
      name=Test
      t1=09:00
      t2=07:00
    """
    wa = (request.args.get("wa") or "").strip()
    name = (request.args.get("name") or "Guest").strip()
    t1 = _parse_hhmm(request.args.get("t1", "09:00"))
    t2 = _parse_hhmm(request.args.get("t2", "07:00"))

    try:
        with db_session() as s:  # type: OrmSession
            # Upsert client
            client = (
                s.query(Client)
                .filter(Client.wa_number == wa)
                .first()
            )
            if not client:
                client = Client(name=name, wa_number=wa)
                s.add(client)
                s.flush()

            # Create sessions for tomorrow and the day after
            d1 = date.today() + timedelta(days=1)
            d2 = date.today() + timedelta(days=2)

            def get_or_create_session(d: date, tt: time) -> Session:
                sess = (
                    s.query(Session)
                    .filter(Session.session_date == d, Session.start_time == tt)
                    .first()
                )
                if not sess:
                    sess = Session(
                        session_date=d,
                        start_time=tt,
                        capacity=8,
                        booked_count=0,
                        status="open",
                    )
                    s.add(sess)
                    s.flush()
                return sess

            s1 = get_or_create_session(d1, t1)
            s2 = get_or_create_session(d2, t2)

            # Create bookings if not exist; increment booked_count
            created = []
            for sess in (s1, s2):
                bk = (
                    s.query(Booking)
                    .filter(Booking.client_id == client.id, Booking.session_id == sess.id)
                    .first()
                )
                if not bk:
                    bk = Booking(client_id=client.id, session_id=sess.id, status="confirmed")
                    s.add(bk)
                    sess.booked_count = (sess.booked_count or 0) + 1
                    created.append({"session_id": sess.id, "status": "confirmed"})

            s.commit()

            return jsonify({
                "ok": True,
                "client": {"id": client.id, "name": client.name, "wa_number": client.wa_number},
                "sessions_created": [
                    {"id": s1.id, "date": s1.session_date.isoformat(), "time": s1.start_time.strftime("%H:%M")},
                    {"id": s2.id, "date": s2.session_date.isoformat(), "time": s2.start_time.strftime("%H:%M")},
                ],
                "bookings": created,
            }), 200

    except Exception as e:
        log.exception("seed_demo failed")
        return jsonify({"ok": False, "error": str(e)}), 500
