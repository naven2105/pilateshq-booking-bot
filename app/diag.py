# app/diag.py
"""
Diagnostic Endpoints
--------------------
Used to verify that the service and integrations are healthy.
"""

import logging
from flask import Blueprint
from sqlalchemy import text
from .db import db_session

diag_bp = Blueprint("diag", __name__)
log = logging.getLogger(__name__)


@diag_bp.get("/diag/ping")
def ping():
    """Simple health check."""
    return {"ok": True, "msg": "pong"}, 200


@diag_bp.get("/diag/db-test")
def db_test():
    """Check DB connection by running SELECT 1."""
    try:
        result = db_session.execute(text("SELECT 1")).scalar()
        return {"ok": True, "result": result}, 200
    except Exception as e:
        log.exception("DB connection failed")
        return {"ok": False, "error": str(e)}, 500
