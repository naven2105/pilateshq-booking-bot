"""
admin_clients.py
────────────────
Handles client management:
 - Add clients
 - Update DOB (with hybrid matching)
 - Update mobile (with hybrid matching)
 - Update name (with hybrid matching)
 - Convert leads
 - Attendance updates (sick, no-show, cancel next session)
 - Deactivate clients
"""

import logging
from sqlalchemy import text
from .db import get_session
from .utils import send_whatsapp_text, normalize_wa, safe_execute
from . import admin_nudge
from .admin_utils import (
    _find_or_create_client,
    _format_dob,
    _find_client_matches,
    _confirm_or_disambiguate,
)

log = logging.getLogger(__name__)


def handle_client_command(parsed: dict, wa: str):
    intent = parsed.get("intent")

    # ── Add client ──────────────────────────────────────────────
    if intent == "add_client":
        name = parsed.get("name")
        num_entered = parsed.get("number")  # as typed by Nadine
        num = normalize_wa(num_entered)
        cid, wa_num, cname, dob = _find_or_create_client(name, num)
        if cid:
            msg = (
                f"✅ New client registered\n\n"
                f"Name: {cname}\n"
                f"Mobile: {num_entered}"
            )
            if dob:
                msg += f"\nDOB: {_format_dob(dob)}"
            safe_execute(send_whatsapp_text, wa, msg, label="client_added")
        else:
            safe_execute(send_whatsapp_text, wa, f"⚠ Could not add client '{name}'.", label="client_add_fail")
        return

    # ── Update DOB ─────────────────────────────────────────────
    if intent == "update_dob":
        name = parsed.get("name")
        new_dob = parsed.get("dob")
        matches = _find_client_matches(name)
        choice = _confirm_or_disambiguate(matches, "update DOB", wa, "<new dob>")
        if not choice:
            return

        cid, cname, _, _ = choice
        with get_session() as s:
            s.execute(
                text("UPDATE clients SET birthday=:dob WHERE id=:cid"),
                {"dob": new_dob, "cid": cid},
            )
        msg = (
            f"📝 DOB updated\n\n"
            f"Name: {cname}\n"
            f"New DOB: {_format_dob(new_dob)}"
        )
        safe_execute(send_whatsapp_text, wa, msg, label="dob_updated")
        return

    # ── Update Mobile ──────────────────────────────────────────
    if intent == "update_mobile":
        name = parsed.get("name")
        num_entered = parsed.get("number")
        new_mobile = normalize_wa(num_entered)

        matches = _find_client_matches(name)
        choice = _confirm_or_disambiguate(matches, "update mobile", wa, "<new mobile>")
        if not choice:
            return

        cid, cname, _, _ = choice
        with get_session() as s:
            s.execute(
                text("UPDATE clients SET wa_number=:wa, phone=:wa WHERE id=:cid"),
                {"wa": new_mobile, "cid": cid},
            )
        msg = (
            f"📱 Mobile updated\n\n"
            f"Name: {cname}\n"
            f"New Mobile: {num_entered}"
        )
        safe_execute(send_whatsapp_text, wa, msg, label="mobile_updated")
        return

    # ── Update Name ────────────────────────────────────────────
    if intent == "update_name":
        old_name = parsed.get("old_name")
        new_name = parsed.get("new_name")

        matches = _find_client_matches(old_name)
        choice = _confirm_or_disambiguate(matches, "update name", wa, f"{new_name}")
        if not choice:
            return

        cid, cname, _, _ = choice
        with get_session() as s:
            s.execute(
                text("UPDATE clients SET name=:new WHERE id=:cid"),
                {"new": new_name, "cid": cid},
            )
        msg = (
            f"✏️ Name updated\n\n"
            f"Old Name: {cname}\n"
            f"New Name: {new_name}"
        )
        safe_execute(send_whatsapp_text, wa, msg, label="name_updated")
        return

    # ── Attendance Updates ─────────────────────────────────────
    if intent in {"off_sick_today", "no_show_today", "cancel_next"}:
        name = parsed.get("name")
        status = intent.replace("_", " ")
        admin_nudge.status_update(name, status)
        return

    # ── Deactivation ──────────────────────────────────────────
    if intent == "deactivate":
        name = parsed.get("name")
        admin_nudge.request_deactivate(name, wa)
        return

    if intent == "confirm_deactivate":
        name = parsed.get("name")
        with get_session() as s:
            s.execute(text("UPDATE clients SET active=false WHERE lower(name)=lower(:n)"), {"n": name.lower()})
        admin_nudge.confirm_deactivate(name, wa)
        return

    if intent == "cancel":
        safe_execute(send_whatsapp_text, wa, "❎ Cancelled.", label="cancel")
        return

    # ── Fallback ──────────────────────────────────────────────
    safe_execute(send_whatsapp_text, wa, "⚠ Unknown client command.", label="client_fallback")
