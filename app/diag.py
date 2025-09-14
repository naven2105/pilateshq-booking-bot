# app/diag.py
"""
Diagnostic Endpoints
--------------------
Lightweight routes to verify service and database connectivity.
Also exposes a simple landing page at '/' so GET / does not 404.
Includes template smoke-test endpoints so you can test delivery without DB rows:
- POST /diag/test-client-template?to=<wa_id>&time=09:00
- POST /diag/test-weekly-template?to=<wa_id>&name=<Name>&items=<semi-colon list>
"""

from __future__ import annotations
import logging
from flask import Blueprint, jsonify, request
from sqlalchemy import text

from .db import db_session
from . import utils, config

diag_bp = Blueprint("diag", __name__)
log = logging.getLogger(__name__)


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
                    "test_weekly_template": "/diag/test-weekly-template?to=<wa_id>&name=<Name>&items=Mon 16 Sep at 09:00;Wed 17 Sep at 07:00",
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


@diag_bp.post("/diag/test-client-template")
def test_client_template():
    """
    Send the 'session_tomorrow' client template without requiring DB bookings.
    Query params:
      - to   : WhatsApp wa_id, e.g. '2773XXXXXXX'
      - time : time string shown to user (e.g., '09:00')
      - tpl  : (optional) template name override; default from config/env
      - lang : (optional) language code override; default from config/env
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
            body_params=[time_str],  # your template expects {{1}} = time only
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
    Send the 'weekly_template_message' template (2 vars) without DB:
      {{1}} = client name
      {{2}} = bullet-list of sessions (one string with newlines)
    Query params:
      - to    : WhatsApp wa_id, e.g. '2773XXXXXXX' (required)
      - name  : client's name (default 'there')
      - items : semi-colon OR comma-separated list of entries, e.g.
                "Mon 16 Sep at 09:00;Wed 17 Sep at 07:00"
      - tpl   : override template (default 'weekly_template_message')
      - lang  : override language (default 'en')
    """
    try:
        to = request.args.get("to", "").strip()
        if not to:
            return {"ok": False, "error": "Missing 'to' (WhatsApp wa_id)."}, 400

        name = request.args.get("name", "there").strip()

        raw_items = request.args.get("items", "").strip()
        if raw_items:
            # split on ';' primarily, fall back to ','
            parts = [p.strip() for p in (raw_items.split(";") if ";" in raw_items else raw_items.split(","))]
            lines = [f"- {p}" for p in parts if p]
        else:
            # default sample lines if none provided
            lines = ["- Mon 16 Sep at 09:00", "- Wed 17 Sep at 07:00"]

        body_list = "\n".join(lines) if lines else "No sessions in the next 7 days."

        template_name = request.args.get("tpl", "weekly_template_message")
        lang_code = request.args.get("lang", "en")

        res = utils.send_whatsapp_template(
            to=to,
            template_name=template_name,
            lang_code=lang_code,
            body_params=[name, body_list],  # {{1}} name, {{2}} list
        )
        code = res.get("status_code", 0)
        return {
            "ok": bool(code and code < 400),
            "to": to,
            "template": template_name,
            "lang": lang_code,
            "status_code": code,
            "vars": {"name": name, "items": lines},
            "response": res.get("response"),
        }, 200 if code and code < 400 else 500

    except Exception as e:
        log.exception("test-weekly-template failed")
        return {"ok": False, "error": str(e)}, 500
