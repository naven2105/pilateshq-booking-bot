"""
router_helpers.py
──────────────────
Shared helper functions for router modules.
"""

import logging
from datetime import datetime
from sqlalchemy import text
from .db import get_session
from .utils import normalize_wa

log = logging.getLogger(__name__)


def _normalize_dob(dob: str | None) -> str | None:
    if not dob:
        return None
    dob = dob.strip()
    for fmt in ("%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(dob, fmt).strftime("%Y-%m-%d")
        except Exception:
            pass
    for fmt in ("%d %B", "%d %b"):
        try:
            dt = datetime.strptime(dob, fmt)
            return dt.replace(year=1900).strftime("%Y-%m-%d")
        except Exception:
            pass
    log.warning(f"[DOB] Could not parse → {dob!r}")
    return None


def _format_dob_display(dob_norm: str | None) -> str:
    if not dob_norm:
        return "N/A"
    try:
        dt = datetime.strptime(dob_norm, "%Y-%m-%d")
        if dt.year == 1900:
            return dt.strftime("%d-%b")
        return dt.strftime("%d-%b-%Y")
    except Exception:
        return "N/A"


def _create_client_record(name: str, mobile: str, dob: str | None):
    """
    Insert client if not exists. Update lead status if present.
    Returns client_id.
    """
    wa = normalize_wa(mobile)
    dob_norm = _normalize_dob(dob)

    with get_session() as s:
        row = s.execute(
            text("SELECT id FROM clients WHERE wa_number=:wa"),
            {"wa": wa},
        ).first()
        if row:
            return row[0]

        r = s.execute(
            text(
                "INSERT INTO clients (name, wa_number, phone, birthday) "
                "VALUES (:n, :wa, :wa, :dob) RETURNING id"
            ),
            {"n": name, "wa": wa, "dob": dob_norm},
        )
        cid = r.scalar()

        s.execute(
            text("UPDATE leads SET status='converted' WHERE wa_number=:wa"),
            {"wa": wa},
        )
        return cid
