# app/public.py
from __future__ import annotations

import re
import logging
from typing import Optional, Tuple

from sqlalchemy import text

from .db import get_session
from .utils import normalize_wa, send_whatsapp_text
from . import crud


# ----------------------------
# Quick, friendly studio FAQs
# ----------------------------
FAQ_ITEMS = [
    ("Address & parking", "We’re at 71 Grant Ave, Norwood, Johannesburg. Safe off-street parking is available."),
    ("Group sizes", "Groups are capped at 6 to keep coaching personal."),
    ("Equipment", "We use Reformers, Wall Units, Wunda chairs, small props, and mats."),
    ("Pricing", "Groups from R180 per session."),
    ("Schedule", "Weekdays 06:00–18:00; Sat 08:00–10:00."),
    ("How to start", "Most people start with a 1:1 assessment before joining groups."),
]


# ----------------------------
# Name parsing & client upsert
# ----------------------------
def _parse_name_from_text(text_in: str) -> Optional[str]:
    """
    Heuristic: treat short, alpha-ish messages as a name.
    Accepts “Sam”, “Sam Mokoena”, “Sam-M”, strips “my name is ...”.
    Reject if digits, too short/long, or odd chars.
    """
    if not text_in:
        return None

    t = text_in.strip()
    t = re.sub(r"^(my\s+name\s+is|name\s*[:\-]?)\s+", "", t, flags=re.I)  # remove lead-in
    if len(t) < 2 or len(t) > 60:
        return None
    if re.search(r"\d", t):
        return None
    if not re.match(r"^[A-Za-z .'\-]+$", t):
        return None
    # Title-case words
    t = " ".join(w.capitalize() for w in re.split(r"\s+", t) if w)
    return t or None


def _upsert_client_by_wa(wa_e164: str, name: Optional[str] = None) -> Tuple[int, bool, bool]:
    """
    Ensure a client row exists for this wa_number.
    Returns (client_id, created_bool, updated_name_bool).
    """
    with get_session() as s:
        row = s.execute(
            text("SELECT id, COALESCE(name,'') AS name FROM clients WHERE wa_number = :wa"),
            {"wa": wa_e164},
        ).mappings().first()

        if row:
            updated = False
            if name and not row["name"]:
                s.execute(text("UPDATE clients SET name = :n WHERE id = :cid"), {"n": name, "cid": row["id"]})
                updated = True
            s.commit()
            return row["id"], False, updated

        ins = s.execute(
            text("""
                INSERT INTO clients (wa_number, name, plan, credits)
                VALUES (:wa, :name, NULL, 0)
                RETURNING id
            """),
            {"wa": wa_e164, "name": name or None},
        ).mappings().first()
        s.commit()
        return ins["id"], True, bool(name)


# ----------------------------
# Public message entry points
# ----------------------------
def handle_public_greeting(sender_wa: str, reply_id: Optional[str] = None) -> str:
    """
    For first contact / greetings from non-admins:
      - Create a lead row (client) if missing.
      - Log inbound.
      - Send welcome, FAQs, and a CTA.
    """
    to = normalize_wa(sender_wa)
    if not to:
        return "invalid number"

    # Log inbound greeting
    crud.log_lead_message(to, "in", "(greeting)")

    # Create lead if absent
    _cid, created, _ = _upsert_client_by_wa(to, name=None)
    if created:
        logging.info(f"[public] created new lead for {to}")

    welcome = (
        "👋 Welcome to *PilatesHQ!*\n"
        "I’m the studio assistant. May I have your *name* so we can personalise your experience?"
    )
    send_whatsapp_text(to, welcome, reply_id)
    crud.log_lead_message(to, "out", welcome)

    faq_lines = ["Here are some quick FAQs you might find useful:"]
    for title, desc in FAQ_ITEMS:
        faq_lines.append(f"• *{title}*: {desc}")
    faq_text = "\n".join(faq_lines)
    send_whatsapp_text(to, faq_text)
    crud.log_lead_message(to, "out", faq_text)

    cta = (
        "If you’d like to *book a 1:1 assessment* or *join a group*, just say:\n"
        "• *Book assessment*\n"
        "• *Show group times*"
    )
    send_whatsapp_text(to, cta)
    crud.log_lead_message(to, "out", cta)

    return "sent"


def handle_public_message(sender_wa: str, text_in: str, reply_id: Optional[str] = None) -> str:
    """
    Catch-all for non-admin inbound messages.
      - If it looks like a name → save it and confirm.
      - If greeting-like → run greeting flow.
      - Else → short help + mini-FAQ.
    Also logs inbound/outbound to lead_messages.
    """
    to = normalize_wa(sender_wa)
    if not to:
        return "invalid number"

    # Log inbound
    incoming = (text_in or "").strip()
    crud.log_lead_message(to, "in", incoming)

    # Try capture a name
    name_guess = _parse_name_from_text(incoming)
    if name_guess:
        _cid, created, updated = _upsert_client_by_wa(to, name=name_guess)
        if created or updated:
            msg = f"Thanks, *{name_guess}*! You’re all set. 😊"
        else:
            msg = f"Great, *{name_guess}*. I’ve got your details on file. ✅"
        send_whatsapp_text(to, msg)
        crud.log_lead_message(to, "out", msg)

        next_steps = (
            "Would you like to *book a 1:1 assessment* to get started, "
            "or see *group schedule* options?"
        )
        send_whatsapp_text(to, next_steps)
        crud.log_lead_message(to, "out", next_steps)
        return "saved-name"

    # Greeting re-trigger
    if re.match(r"^\s*(hi|hello|hey|morning|afternoon|evening)\s*$", incoming, flags=re.I):
        return handle_public_greeting(sender_wa, reply_id)

    # Default assist
    help_text = (
        "I can help with *pricing*, *schedule*, *address*, and *how to start*.\n"
        "Reply with one of these keywords: *pricing*, *schedule*, *address*, *start*."
    )
    send_whatsapp_text(to, help_text)
    crud.log_lead_message(to, "out", help_text)

    mini = []
    for title, desc in FAQ_ITEMS[:3]:
        mini.append(f"• *{title}*: {desc}")
    mini_text = "\n".join(mini)
    send_whatsapp_text(to, mini_text)
    crud.log_lead_message(to, "out", mini_text)

    return "helped"
