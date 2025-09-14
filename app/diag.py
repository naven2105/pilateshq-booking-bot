# app/diag.py
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, time
from typing import Dict, List, Tuple

from flask import Blueprint, jsonify, request
from sqlalchemy import text
from sqlalchemy.orm import Session as OrmSession

from .db import db_session
from .models import Client, Session, Booking
from . import utils
from .config import TEMPLATE_LANG

log = logging.getLogger(__name__)
diag_bp = Blueprint("diag", __name__)

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _fmt_hhmm(t: time) -> str:
    return t.strftime("%H:%M")

def _lang_candidates(preferred: str | None) -> List[str]:
    # Try env first, then safe fallbacks commonly used with WA templates
    cand = [x for x in [preferred, "en", "en_US", "en_ZA"] if x]
    seen, out = set(), []
    for c in cand:
        if c not in seen:
            out.append(c)
            seen.add(c)
    return out

def _send_template_with_fallback(to: str, template: str, variables: Dict[str, str], preferred_lang: str | None):
    for lang in _lang_candidates(preferred_lang):
        ok, status, resp = utils.send_template(to=to, template=template, lang=lang, variables=variables)
        log.info("[diag tpl-send] to=%s tpl=%s lang=%s status=%s ok=%s", to, template, lang, status, ok)
        if ok:
            return ok, status, resp, lang
    return False, 0, {"error": "all language attempts failed"}, None

# ──────────────────────────────────────────────────────────────────────────────
# Root + DB test + Cron status
# ──────────────────────────────────────────────────────────────────────────────

@diag_bp.get("/")
def root():
    return "PilatesHQ bot is up.", 200

@diag_bp.get("/diag/db-test")
def db_test():
    try:
        with db_session() as s:  # type: OrmSession
            # SQLAlchemy 2.x requires text() for textual SQL
            val = s.execute(text("SELECT 1")).scalar_one()
            return jsonify({"ok": True, "result": int(val)})
    except Exception:
        log.exception("db-test failed")
        return "error", 500

@diag_bp.get("/diag/cron-status")
def cron_status():
    # Best-effort: read counters/timestamps if utils/tasks expose them; otherwise default
    last_run = getattr(utils, "LAST_RUN", {})
    error_counters = getattr(utils, "ERROR_COUNTERS", {})
    return jsonify({
        "ok": True,
        "server_time": datetime.now().isoformat(timespec="seconds"),
        "last_run": last_run,
        "error_counters": error_counters,
    })

# ──────────────────────────────────────────────────────────────────────────────
# Template smoke tests
# ──────────────────────────────────────────────────────────────────────────────

@diag_bp.post("/diag/test-client-template")
def test_client_template():
    """
    Smoke test for 'session_tomorrow' template with language fallback.
    Params: to=MSISDN, time=HH:MM
    """
    to = request.args.get("to", "").strip()
    hhmm = request.args.get("time", "09:00").strip()
    ok, status, resp, lang = _send_template_with_fallback(
        to=to,
        template="session_tomorrow",
        variables={"1": hhmm},
        preferred_lang=TEMPLATE_LANG,
    )
    code = 200 if ok else 500
    return jsonify({
        "ok": ok,
        "status_code": status,
        "response": resp,
        "to": to,
        "template": "session_tomorrow",
        "lang": lang or TEMPLATE_LANG or "en",
    }), code

@diag_bp.post("/diag/test-weekly-template")
def test_weekly_template():
    """
    Smoke test for 'weekly_template_message'.
    Params: to=MSISDN, name=..., items="Mon 15 Sep 09:00;Tue 16 Sep 07:00"
    We convert ';' separated items into a single Meta-safe string joined with ' • '.
    """
    to = request.args.get("to", "").strip()
    name = request.args.get("name", "there").strip()
    items = request.args.get("items", "").strip()
    if ";" in items:
        parts = [p.strip() for p in items.split(";") if p.strip()]
        items_str = " • ".join(parts)
    else:
        items_str = items

    # Meta-safe: collapse whitespace
    items_str = " ".join(items_str.split())
    name_str = " ".join(name.split())

    ok, status, resp, lang = _send_template_with_fallback(
        to=to,
        template="weekly_template_message",
        variables={"name": name_str, "items": items_str},
        preferred_lang=TEMPLATE_LANG,
    )
    code = 200 if ok else 500
    return jsonify({
        "ok": ok,
        "status_code": status,
        "response": resp,
        "to": to,
        "template": "weekly_template_message",
        "lang": lang or TEMPLATE_LANG or "en",
        "vars": {"name": name_str, "items": items_str},
    }), code

# ──────────────────────────────────────────────────────────────────────────────
# Weekly dry-run (no sends): see which bookings would be messaged
# ──────────────────────────────────────────────────────────────────────────────

@diag_bp.get("/diag/weekly-dry-run")
def weekly_dry_run():
    try:
        window_days = int(request.args.get("days", "7"))
        status_in = request.args.get("status_in", "confirmed").split(",")
        include_null_wa = request.args.get("include_null_wa", "0") in ("1", "true", "True")

        start = date.today()
        end = start + timedelta(days=max(1, window_days) - 1)

        with db_session() as s:
            q = (
                s.query(
                    Client.id.label("client_id"),
                    Client.name.label("client_name"),
                    Client.wa_number.label("wa_number"),
                    Booking.status.label("booking_status"),
                    Session.session_date.label("session_date"),
                    Session.start_time.label("start_time"),
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
                if include_null_wa or has_wa:
                    sample.append({
                        "client_id": r.client_id,
                        "client_name": r.client_name,
                        "wa_number": r.wa_number,
                        "booking_status": r.booking_status,
                        "session_date": str(r.session_date),
                        "start_time": str(r.start_time),
                        "would_send": has_wa,
                    })

            return jsonify({
                "ok": True,
                "window_days": window_days,
                "status_in": status_in,
                "include_null_wa": include_null_wa,
                "total_matches": len(rows),
                "with_wa_number": with_wa,
                "without_wa_number": without_wa,
                "sample_first_100": sample[:100],
            })
    except Exception:
        log.exception("weekly-dry-run failed")
        return "error", 500

# ──────────────────────────────────────────────────────────────────────────────
# Seed demo data: upsert client + two sessions + bookings
# ──────────────────────────────────────────────────────────────────────────────

@diag_bp.post("/diag/seed-demo")
def seed_demo():
    """
    Seed a single client and two sessions on the next two days:
      /diag/seed-demo?wa=2773...&name=Test&t1=09:00&t2=07:00
    """
    try:
        wa = (request.args.get("wa") or "").strip()
        nm = (request.args.get("name") or "Test").strip()
        t1 = (request.args.get("t1") or "09:00").strip()
        t2 = (request.args.get("t2") or "07:00").strip()

        d1 = date.today() + timedelta(days=1)
        d2 = d1 + timedelta(days=1)

        def parse_hhmm(s: str) -> time:
            hh, mm = s.split(":")
            return time(hour=int(hh), minute=int(mm))

        with db_session() as s:  # type: OrmSession
            # Upsert client by wa_number
            c = s.query(Client).filter(Client.wa_number == wa).first()
            if not c:
                c = Client(name=nm, wa_number=wa)
                s.add(c)
                s.flush()
            else:
                c.name = nm

            # Ensure two sessions exist (by date/time)
            sess1 = (
                s.query(Session)
                .filter(Session.session_date == d1, Session.start_time == parse_hhmm(t1))
                .first()
            )
            if not sess1:
                sess1 = Session(
                    session_date=d1,
                    start_time=parse_hhmm(t1),
                    capacity=6,
                    booked_count=0,
                    status="open",
                )
                s.add(sess1)
                s.flush()

            sess2 = (
                s.query(Session)
                .filter(Session.session_date == d2, Session.start_time == parse_hhmm(t2))
                .first()
            )
            if not sess2:
                sess2 = Session(
                    session_date=d2,
                    start_time=parse_hhmm(t2),
                    capacity=6,
                    booked_count=0,
                    status="open",
                )
                s.add(sess2)
                s.flush()

            # Create (or ensure) bookings for client
            b1 = (
                s.query(Booking)
                .filter(Booking.client_id == c.id, Booking.session_id == sess1.id)
                .first()
            )
            if not b1:
                b1 = Booking(client_id=c.id, session_id=sess1.id, status="confirmed")
                s.add(b1)
                sess1.booked_count = (sess1.booked_count or 0) + 1

            b2 = (
                s.query(Booking)
                .filter(Booking.client_id == c.id, Booking.session_id == sess2.id)
                .first()
            )
            if not b2:
                b2 = Booking(client_id=c.id, session_id=sess2.id, status="confirmed")
                s.add(b2)
                sess2.booked_count = (sess2.booked_count or 0) + 1

            s.flush()

            return jsonify({
                "ok": True,
                "client": {"id": c.id, "name": c.name, "wa_number": c.wa_number},
                "sessions_created": [
                    {"id": sess1.id, "date": str(sess1.session_date), "time": _fmt_hhmm(sess1.start_time)},
                    {"id": sess2.id, "date": str(sess2.session_date), "time": _fmt_hhmm(sess2.start_time)},
                ],
                "bookings": [
                    {"session_id": sess1.id, "status": "confirmed"},
                    {"session_id": sess2.id, "status": "confirmed"},
                ],
            })
    except Exception as e:
        log.exception("seed_demo failed")
        return jsonify({"ok": False, "error": str(e)}), 500
