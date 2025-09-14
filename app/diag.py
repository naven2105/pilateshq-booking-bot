# app/diag.py
"""
Diagnostic Endpoints
--------------------
Lightweight routes to verify service, database connectivity, template sends,
and (NEW) seed demo data for testing.

Routes:
- GET  /                           : Landing JSON (so GET / isn’t 404)
- GET  /diag/ping                  : Health check
- GET  /diag/db-test               : DB connectivity test
- POST /diag/test-client-template  : Send 'session_tomorrow' to a target number
- POST /diag/test-weekly-template  : Send 'weekly_template_message' with manual items
- GET  /diag/weekly-dry-run        : Preview weekly reminder candidates from DB
- POST /diag/seed-demo             : Create/ensure demo Client/Sessions/Bookings (idempotent)

Windows CMD examples:
  curl -s -i -X POST "https://<host>/diag/seed-demo?wa=27735534607&name=Test&t1=09:00&t2=07:00" -H "Content-Type: application/json" --data "{}"
"""

from __future__ import annotations
import logging
import re
from typing import List, Dict, Any, Optional
from datetime import date, datetime, timedelta, time as dtime

from flask import Blueprint, jsonify, request
from sqlalchemy import text, and_, cast, String, func

from .db import db_session
from . import utils, config
from .models import Client, Booking, Session

diag_bp = Blueprint("diag", __name__)
log = logging.getLogger(__name__)

# ---------- Helpers for template param sanitation (avoid WhatsApp 132018) ----------
_SPACE_COLLAPSE = re.compile(r"\s+")
_FIVE_SPACES_OR_MORE = re.compile(r" {5,}")

def _sanitize_param(text_val: str) -> str:
    """
    Make a template variable safe:
    - Replace \r, \n, \t with a single space
    - Collapse runs of whitespace
    - Prevent >4 consecutive spaces
    - Trim to <= 1024 chars (Cloud API body param limit)
    """
    if not text_val:
        return ""
    t = text_val.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    t = _SPACE_COLLAPSE.sub(" ", t)
    t = _FIVE_SPACES_OR_MORE.sub("    ", t)  # cap at 4 spaces
    return t.strip()[:1024]

def _parse_hhmm(s: str) -> Optional[dtime]:
    try:
        hh, mm = s.strip().split(":")
        return dtime(hour=int(hh), minute=int(mm))
    except Exception:
        return None

def _time_hhmm(t) -> str:
    try:
        return t.strftime("%H:%M")
    except Exception:
        return str(t)

def _fmt_weekly_item(d: date, t) -> str:
    try:
        return f"{d.strftime('%a %d %b')} {_time_hhmm(t)}"
    except Exception:
        return f"{d} {_time_hhmm(t)}"

# ---------- Landing / health ----------
@diag_bp.get("/")
def root():
    """Simple landing page for uptime checks."""
    return (
        jsonify(
            {
                "ok": True,
                "service": "PilatesHQ Booking Bot",
                "endpoints": {
                    "ping": "/diag/ping",
                    "db_test": "/diag/db-test",
                    "tasks_daily": "/tasks/run-reminders?daily=1",
                    "tasks_tomorrow": "/tasks/run-reminders?tomorrow=1",
                    "tasks_next_hour": "/tasks/run-reminders?next=1",
                    "tasks_weekly": "/tasks/run-reminders?weekly=1",
                    "test_client_template": "/diag/test-client-template?to=<wa_id>&time=09:00",
                    "test_weekly_template": "/diag/test-weekly-template?to=<Name>&items=Mon 16 Sep 09:00;Wed 17 Sep 07:00",
                    "weekly_dry_run": "/diag/weekly-dry-run?days=7&status_in=confirmed&include_null_wa=0",
                    "seed_demo": "/diag/seed-demo?wa=27735534607&name=Test&t1=09:00&t2=07:00",
                },
            }
        ),
        200,
    )

@diag_bp.get("/diag/ping")
def ping():
    """Simple health check."""
    return {"ok": True, "msg": "pong"}, 200

@diag_bp.get("/diag/db-test")
def db_test():
    """Check DB connection by running SELECT 1."""
    try:
        result = db_session.execute(text("SELECT 1")).scalar()
        return {"ok": True, "result": int(result)}, 200
    except Exception as e:
        log.exception("DB connection failed")
        return {"ok": False, "error": str(e)}, 500

# ---------- Template smoke tests ----------
@diag_bp.post("/diag/test-client-template")
def test_client_template():
    """
    Send 'session_tomorrow' without requiring DB bookings.
    Query: to, time, tpl (opt), lang (opt)
    """
    try:
        to = request.args.get("to", "").strip()
        time_str = request.args.get("time", "09:00").strip()
        if not to:
            return {"ok": False, "error": "Missing 'to' (WhatsApp wa_id)."}, 400

        template_name = request.args.get(
            "tpl",
            getattr(config, "CLIENT_TEMPLATE_TOMORROW", "session_tomorrow"),
        )
        lang_code = request.args.get(
            "lang",
            getattr(config, "CLIENT_TEMPLATE_TOMORROW_LANG", "en_US"),
        )

        res = utils.send_whatsapp_template(
            to=to,
            template_name=template_name,
            lang_code=lang_code,
            body_params=[_sanitize_param(time_str)],  # {{1}} = time only
        )
        code = res.get("status_code", 0)
        return {
            "ok": bool(code and code < 400),
            "to": to,
            "template": template_name,
            "lang": lang_code,
            "status_code": code,
            "response": res.get("response"),
        }, 200 if code and code < 400 else 500

    except Exception as e:
        log.exception("test-client-template failed")
        return {"ok": False, "error": str(e)}, 500

@diag_bp.post("/diag/test-weekly-template")
def test_weekly_template():
    """
    Send 'weekly_template_message' (2 vars) without DB:
      {{1}} name, {{2}} single-line session list (no newlines/tabs)
    Query: to (req), name, items, tpl, lang
    """
    try:
        to = request.args.get("to", "").strip()
        if not to:
            return {"ok": False, "error": "Missing 'to' (WhatsApp wa_id)."}, 400

        name = request.args.get("name", "there").strip()
        raw_items = request.args.get("items", "").strip()
        if raw_items:
            parts = [p.strip() for p in (raw_items.split(";") if ";" in raw_items else raw_items.split(","))]
            flat_parts = [_sanitize_param(p) for p in parts if p]
        else:
            flat_parts = ["Mon 16 Sep 09:00", "Wed 17 Sep 07:00"]

        list_single_line = _sanitize_param(" • ".join(flat_parts))

        template_name = request.args.get("tpl", "weekly_template_message")
        lang_code = request.args.get("lang", "en")

        res = utils.send_whatsapp_template(
            to=to,
            template_name=template_name,
            lang_code=lang_code,
            body_params=[_sanitize_param(name), list_single_line],  # {{1}} name, {{2}} list
        )
        code = res.get("status_code", 0)
        return {
            "ok": bool(code and code < 400),
            "to": to,
            "template": template_name,
            "lang": lang_code,
            "status_code": code,
            "vars": {"name": _sanitize_param(name), "items": list_single_line},
            "response": res.get("response"),
        }, 200 if code and code < 400 else 500

    except Exception as e:
        log.exception("test-weekly-template failed")
        return {"ok": False, "error": str(e)}, 500

# ---------- Weekly dry run ----------
@diag_bp.get("/diag/weekly-dry-run")
def weekly_dry_run():
    """
    Preview which rows would be used for weekly reminders (no sends).
    Query params:
      - days: window length from today (default 7)
      - status_in: comma-separated statuses to include (default "confirmed")
      - include_null_wa: 0/1 include clients without wa_number in the result
    """
    try:
        try:
            days = int(request.args.get("days", "7"))
            if days < 1:
                days = 7
        except Exception:
            days = 7

        status_in_raw = request.args.get("status_in", "confirmed").strip()
        status_list = [s.strip() for s in status_in_raw.split(",") if s.strip()]
        include_null_wa = request.args.get("include_null_wa", "0") in ("1", "true", "True")

        start = date.today()
        end = start + timedelta(days=days)

        q = (
            db_session.query(
                Client.id.label("client_id"),
                Client.name.label("client_name"),
                Client.wa_number.label("wa_number"),
                Session.session_date.label("session_date"),
                Session.start_time.label("start_time"),
                cast(Booking.status, String).label("booking_status"),
            )
            .join(Booking, Booking.client_id == Client.id)
            .join(Session, Booking.session_id == Session.id)
            .filter(
                and_(
                    Session.session_date >= start,
                    Session.session_date <= end,
                    cast(Booking.status, String).in_(status_list) if status_list else text("TRUE"),
                    (Client.wa_number.isnot(None)) if not include_null_wa else text("TRUE"),
                )
            )
            .order_by(Client.wa_number, Session.session_date, Session.start_time)
        )

        rows = q.limit(1000).all()
        preview: List[Dict[str, Any]] = []
        for r in rows[:100]:
            preview.append(
                {
                    "client_id": r.client_id,
                    "client_name": r.client_name,
                    "wa_number": r.wa_number,
                    "session_date": str(r.session_date),
                    "start_time": str(r.start_time),
                    "booking_status": r.booking_status,
                    "would_send": bool(r.wa_number),
                }
            )

        total_rows = len(rows)
        with_wa = sum(1 for r in rows if r.wa_number)
        without_wa = total_rows - with_wa

        return {
            "ok": True,
            "window_days": days,
            "status_in": status_list,
            "include_null_wa": include_null_wa,
            "total_matches": total_rows,
            "with_wa_number": with_wa,
            "without_wa_number": without_wa,
            "sample_first_100": preview,
        }, 200

    except Exception as e:
        log.exception("weekly_dry_run failed")
        return {"ok": False, "error": str(e)}, 500

# ---------- Seed demo data ----------
@diag_bp.post("/diag/seed-demo")
def seed_demo():
    """
    Create or ensure demo data for testing reminders/queries:
      - Client(wa_number=<wa>, name=<name>)
      - Session(tomorrow @ t1), Session(+2 days @ t2)
      - Booking(client<->each session, status='confirmed')
    Query params:
      - wa   : WhatsApp number (digits only). Default 27735534607
      - name : Client name. Default 'Test'
      - t1   : HH:MM time for tomorrow (default 09:00)
      - t2   : HH:MM time for +2 days (default 07:00)
    Idempotent: will not duplicate sessions/bookings if they already exist.
    """
    try:
        wa = "".join(ch for ch in request.args.get("wa", "27735534607") if ch.isdigit())
        name = request.args.get("name", "Test").strip() or "Test"
        t1 = _parse_hhmm(request.args.get("t1", "09:00")) or dtime(hour=9, minute=0)
        t2 = _parse_hhmm(request.args.get("t2", "07:00")) or dtime(hour=7, minute=0)

        d1 = date.today() + timedelta(days=1)
        d2 = date.today() + timedelta(days=2)

        # 1) Upsert client by wa_number (or by name if needed)
        client = (
            db_session.query(Client)
            .filter(
                (Client.wa_number == wa) if wa else text("FALSE")
            )
            .first()
        )
        if not client:
            client = Client(name=name, wa_number=wa)
            db_session.add(client)
            db_session.flush()  # get client.id

        # 2) Ensure sessions exist (unique by date & time)
        s1 = (
            db_session.query(Session)
            .filter(and_(Session.session_date == d1, Session.start_time == t1))
            .first()
        )
        if not s1:
            s1 = Session(
                session_date=d1,
                start_time=t1,
                capacity=6 if hasattr(Session, "capacity") else None,
                booked_count=0 if hasattr(Session, "booked_count") else None,
                status="open" if hasattr(Session, "status") else None,
            )
            db_session.add(s1)
            db_session.flush()

        s2 = (
            db_session.query(Session)
            .filter(and_(Session.session_date == d2, Session.start_time == t2))
            .first()
        )
        if not s2:
            s2 = Session(
                session_date=d2,
                start_time=t2,
                capacity=6 if hasattr(Session, "capacity") else None,
                booked_count=0 if hasattr(Session, "booked_count") else None,
                status="open" if hasattr(Session, "status") else None,
            )
            db_session.add(s2)
            db_session.flush()

        # 3) Ensure bookings exist & confirmed
        def _ensure_booking(sess: Session):
            bk = (
                db_session.query(Booking)
                .filter(and_(Booking.session_id == sess.id, Booking.client_id == client.id))
                .first()
            )
            if not bk:
                bk = Booking(session_id=sess.id, client_id=client.id, status="confirmed")
                db_session.add(bk)
            else:
                bk.status = "confirmed"
            return bk

        b1 = _ensure_booking(s1)
        b2 = _ensure_booking(s2)

        db_session.commit()

        return {
            "ok": True,
            "client": {"id": getattr(client, "id", None), "name": client.name, "wa_number": client.wa_number},
            "sessions_created": [
                {"id": getattr(s1, "id", None), "date": str(s1.session_date), "time": _time_hhmm(s1.start_time)},
                {"id": getattr(s2, "id", None), "date": str(s2.session_date), "time": _time_hhmm(s2.start_time)},
            ],
            "bookings": [
                {"session_id": getattr(b1, "session_id", None), "status": getattr(b1, "status", None)},
                {"session_id": getattr(b2, "session_id", None), "status": getattr(b2, "status", None)},
            ],
        }, 200

    except Exception as e:
        log.exception("seed_demo failed")
        db_session.rollback()
        return {"ok": False, "error": str(e)}, 500
