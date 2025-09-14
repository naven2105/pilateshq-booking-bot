    # app/diag.py
"""
Diagnostic Endpoints
--------------------
Lightweight routes to verify service and database connectivity.
Also exposes a simple landing page at '/' so GET / does not 404.
"""

import logging
from flask import Blueprint, jsonify
from sqlalchemy import text
from .db import db_session

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
