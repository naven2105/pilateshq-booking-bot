# app/prospect.py
from __future__ import annotations
import logging
from sqlalchemy import text
from .db import get_session
from .utils import send_whatsapp_text, normalize_wa
from .config import NADINE_WA

log = logging.getLogger(__name__)

WELCOME = (
    "Hi! 👋 I’m PilatesHQ’s assistant.\n"
    "Before we continue, what’s your name?"
)

HANDOVER = (
    "Hi {name}, Nadine has received your enquiry. "
    "She will contact you very soon 💜"
)


def _lead_get_or_create(wa: str):
    """Return existing lead or create placeholder row."""
    with get_session() as s:
        row = s.execute(
            text("SELECT id, name, status FROM leads WHERE wa_number=:wa"),
            {"wa": wa},
        ).mappings().first()
        if row:
            return dict(row)

        # Insert a new blank lead
        s.execute(
            text("INSERT INTO leads (wa_number, status) VALUES (:wa, 'new') "
                 "ON CONFLICT DO NOTHING"),
            {"wa": wa},
        )
        return {"id": None, "name": None, "status": "new"}


def _lead_update_name(wa: str, name: str):
    with get_session() as s:
        s.execute(
            text("UPDATE leads SET name=:name, last_contact=now() WHERE wa_number=:wa"),
            {"name": name, "wa": wa},
        )


def _notify_admin(text_msg: str):
    try:
        if NADINE_WA:
            send_whatsapp_text(normalize_wa(NADINE_WA), text_msg)
    except Exception:
        logging.exception("Failed to notify admin")


def start_or_resume(wa_number: str, incoming_text: str):
    """
    Entry point for unknown numbers.
    Always greets, requests name, then hands off to Nadine.
    """
    wa = normalize_wa(wa_number)
    lead = _lead_get_or_create(wa)
    msg = (incoming_text or "").strip()

    # Step 1: No name yet → ask for it
    if not lead.get("name"):
        if not msg:
            send_whatsapp_text(wa, WELCOME)
            return
        # Store the reply as their name
        name = msg.split()[0].title()
        _lead_update_name(wa, name)
        send_whatsapp_text(wa, HANDOVER.format(name=name))
        _notify_admin(f"📥 New lead: {name} ({wa})")
        return

    # Step 2: Name already known → always reassure & notify Nadine
    name = lead.get("name", "there").split()[0].title()
    send_whatsapp_text(wa, HANDOVER.format(name=name))
    _notify_admin(f"📥 Lead follow-up: {name} ({wa})")
