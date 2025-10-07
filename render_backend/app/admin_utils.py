"""
admin_utils.py
──────────────
Shared utilities for admin modules:
 - Client lookup and creation
 - DOB formatting
 - Hybrid (SQL + fuzzy) client matching
 - Disambiguation helper
"""

import logging
from datetime import datetime
from difflib import get_close_matches
from sqlalchemy import text
from .db import get_session
from .utils import send_whatsapp_text, safe_execute

log = logging.getLogger(__name__)


def _find_or_create_client(name: str, wa_number: str | None = None):
    """Look up a client by name. If not found and wa_number is given, create."""
    with get_session() as s:
        row = s.execute(
            text("SELECT id, wa_number, name, birthday FROM clients WHERE lower(name)=lower(:n)"),
            {"n": name},
        ).first()
        if row:
            return row[0], row[1], row[2], row[3]
        if wa_number:
            r = s.execute(
                text("INSERT INTO clients (name, wa_number, phone) VALUES (:n, :wa, :wa) RETURNING id"),
                {"n": name, "wa": wa_number},
            )
            cid = r.scalar()
            return cid, wa_number, name, None
    return None, None, None, None


def _format_dob(dob: str | None) -> str | None:
    """Format DOB as DD-MMM (ignore year)."""
    if not dob:
        return None
    try:
        dt = datetime.strptime(dob, "%Y-%m-%d")
        return dt.strftime("%d-%b")
    except Exception:
        return dob  # fallback to raw if parsing fails


def _find_client_matches(name: str):
    """Return list of possible matching clients using hybrid fuzzy + SQL search."""
    with get_session() as s:
        rows = s.execute(text("SELECT id, name, wa_number, birthday FROM clients")).fetchall()

    if not rows:
        return []

    all_clients = [r[1] for r in rows]  # all names
    # Fuzzy candidates
    fuzzy_matches = set(get_close_matches(name, all_clients, n=5, cutoff=0.6))

    # SQL-style substring match (case-insensitive)
    sql_matches = [r for r in rows if name.lower() in r[1].lower()]

    # Combine
    final = []
    for r in rows:
        if r[1] in fuzzy_matches or r in sql_matches:
            final.append(r)

    return final


def _confirm_or_disambiguate(matches, action: str, wa: str, extra: str = ""):
    """If one match, return it. If many, ask Nadine to choose."""
    if not matches:
        safe_execute(
            send_whatsapp_text,
            wa,
            f"⚠ No client found. Could not {action}.",
            label=f"{action}_not_found",
        )
        return None

    if len(matches) == 1:
        return matches[0]

    # Multiple matches → send disambiguation
    msg = f"⚠ Multiple matches found. Please refine:\n\n"
    for idx, (cid, cname, cwa, dob) in enumerate(matches, start=1):
        dob_fmt = _format_dob(dob)
        msg += f"{idx}. {cname} ({cwa})"
        if dob_fmt:
            msg += f" DOB {dob_fmt}"
        msg += "\n"
    msg += f"\nReply with: {action} <full name> {extra}".strip()

    safe_execute(send_whatsapp_text, wa, msg, label=f"{action}_disambiguation")
    return None
