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
    "Before we continue, please tell me your *first name*?"
)

INTEREST_PROMPT = (
    "Hi {name}, thanks for your enquiry! Nadine has received your details and will contact you very soon. 🙌\n\n"
    "Meanwhile, would you like to:\n"
    "1) Learn more about PilatesHQ\n"
    "2) Book a session\n\n"
    "Reply with 1–2."
)

# Common greetings to ignore as "names"
IGNORED_NAMES = {"hi", "hello", "hey", "heyy", "heya", "howzit"}


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
    lower = msg.lower()

    # ── Case 1: No name stored yet ─────────────────────────────
    if not lead.get("name"):
        if msg and lower not in IGNORED_NAMES:
            # Save name exactly as typed
            _lead_update(wa, name=msg)
            send_whatsapp_text(wa, INTEREST_PROMPT.format(name=msg.strip().title()))
            _notify_admin(f"📥 New lead: {msg.strip().title()} made an enquiry.")
            return
        else:
            # Ask again if they typed "hi"/"hello" or nothing
            send_whatsapp_text(wa, WELCOME)
            return

    # ── Case 2: Already have their name ───────────────────────
    if msg.isdigit():
        n = int(msg)
        if n == 1:
            send_whatsapp_text(wa, FAQ_MENU_TEXT + "\n\nReply 0 to go back.")
            return
        if n == 2:
            send_whatsapp_text(
                wa,
                "Awesome! 🙌 Nadine will contact you shortly to schedule your first session."
            )
            return
        if n == 0:
            send_whatsapp_text(wa, INTEREST_PROMPT.format(name=lead.get("name", "there")))
            return

    # FAQ lookup
    if len(msg) == 1 and msg.isdigit():
        idx = int(msg) - 1
        if 0 <= idx < len(FAQ_ITEMS):
            title, answer = FAQ_ITEMS[idx]
            send_whatsapp_text(wa, f"*{title}*\n{answer}\n\nReply 0 for main menu.")
            return

    # Default: resend interest menu
    send_whatsapp_text(wa, INTEREST_PROMPT.format(name=lead.get("name", "there")))
