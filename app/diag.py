# app/diag.py
"""
Diagnostic Endpoints
--------------------
Lightweight routes to verify service and database connectivity.
Also exposes a simple landing page at '/' so GET / does not 404.
Includes a template smoke-test endpoint to send a client template without DB rows.
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
            "ok": code and code < 400,
            "to": to,
            "template": template_name,
            "lang": lang_code,
            "status_code": code,
            "response": res.get("response"),
        }, 200 if code and code < 400 else 500

    except Exception as e:
        log.exception("test-client-template failed")
        return {"ok": False, "error": str(e)}, 500
