# app/prospect.py
from __future__ import annotations
import logging
from sqlalchemy import text
from .db import get_session
from .utils import send_whatsapp_text, normalize_wa
from .faqs import FAQ_ITEMS, FAQ_MENU_TEXT
from .config import NADINE_WA

WELCOME = (
    "Hi! 👋 I’m PilatesHQ’s assistant.\n"
    "Before we continue, what’s your name?"
)

INTEREST_PROMPT = (
    "Hi {name}, thanks for your enquiry! Nadine has received your details "
    "and will contact you very soon. 🙌\n\n"
    "Meanwhile, would you like to:\n"
    "1) Learn more about PilatesHQ\n"
    "2) Book a session\n\n"
    "Reply with 1–2."
)


def _lead_get_or_create(wa: str):
    with get_session() as s:
        row = s.execute(
            text("SELECT id, name, interest, status FROM leads WHERE wa_number=:wa"),
            {"wa": wa},
        ).mappings().first()
        if row:
            return dict(row)
        s.execute(
            text("INSERT INTO leads (wa_number) VALUES (:wa) ON CONFLICT DO NOTHING"),
            {"wa": wa},
        )
        return {"id": None, "name": None, "interest": None, "status": "new"}


def _lead_update(wa: str, **fields):
    if not fields:
        return
    sets = ", ".join([f"{k}=:{k}" for k in fields.keys()])
    fields["wa"] = wa
    with get_session() as s:
        s.execute(
            text(f"UPDATE leads SET {sets}, last_contact=now() WHERE wa_number=:wa"),
            fields,
        )


def _mark_lead_converted(wa: str, client_id: int):
    """Mark a lead as converted into a client."""
    with get_session() as s:
        s.execute(
            text("UPDATE leads SET status='converted', client_id=:cid WHERE wa_number=:wa"),
            {"cid": client_id, "wa": wa},
        )


def _notify_admin(text_msg: str):
    try:
        if NADINE_WA:
            send_whatsapp_text(normalize_wa(NADINE_WA), text_msg)
    except Exception:
        logging.exception("Failed to notify admin")


def start_or_resume(wa_number: str, incoming_text: str):
    """Entry point for unknown numbers from router."""
    wa = normalize_wa(wa_number)
    lead = _lead_get_or_create(wa)

    msg = (incoming_text or "").strip()

    # Always greet first-time numbers
    if not lead.get("name"):
        if msg:
            _lead_update(wa, name=msg)
            send_whatsapp_text(
                wa,
                INTEREST_PROMPT.format(name=msg.split()[0].title())
            )
            _notify_admin(f"📥 New lead: {msg} (name captured).")
            return
        send_whatsapp_text(wa, WELCOME)
        return

    lower = msg.lower()
    if any(k in lower for k in ["faq", "questions", "info", "help", "menu"]):
        send_whatsapp_text(wa, FAQ_MENU_TEXT + "\n\nReply 0 to go back.")
        return

    if msg.isdigit():
        n = int(msg)
        if n == 1:
            send_whatsapp_text(wa, FAQ_MENU_TEXT + "\n\nReply 0 to go back.")
            return
        if n == 2:
            _lead_update(wa, interest="session", status="new")
            send_whatsapp_text(
                wa,
                "Perfect! Nadine will contact you shortly to arrange your session. 🙌"
            )
            _notify_admin(f"📥 Lead: {lead.get('name') or wa} wants to book a session.")
            return
        if n == 0:
            send_whatsapp_text(
                wa,
                INTEREST_PROMPT.format(name=lead.get("name", "there"))
            )
            return

    if lower in ("yes", "y"):
        send_whatsapp_text(wa, FAQ_MENU_TEXT + "\n\nReply 0 to go back.")
        return
    if lower in ("no", "n"):
        send_whatsapp_text(
            wa,
            "No problem! If you change your mind, just say “FAQ” or reply with 1–2 anytime."
        )
        return

    if len(msg) == 1 and msg.isdigit():
        idx = int(msg) - 1
        if 0 <= idx < len(FAQ_ITEMS):
            title, answer = FAQ_ITEMS[idx]
            send_whatsapp_text(wa, f"*{title}*\n{answer}\n\nReply 0 for main menu.")
            return

    send_whatsapp_text(
        wa,
        INTEREST_PROMPT.format(name=lead.get("name", "there"))
    )
