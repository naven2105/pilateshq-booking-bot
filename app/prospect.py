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
    "Great to meet you, {name}! Would you like to:\n"
    "1) Book a taster/assessment\n"
    "2) Join a group class\n"
    "3) Book a private (1:1)\n"
    "4) Just browse FAQs\n\n"
    "Reply with 1–4."
)

def _lead_get_or_create(wa: str):
    with get_session() as s:
        row = s.execute(text("SELECT id, name, interest, status FROM leads WHERE wa_number=:wa"), {"wa": wa}).mappings().first()
        if row:
            return dict(row)
        s.execute(text("INSERT INTO leads (wa_number) VALUES (:wa) ON CONFLICT DO NOTHING"), {"wa": wa})
        s.commit()
        return {"id": None, "name": None, "interest": None, "status": "new"}

def _lead_update(wa: str, **fields):
    if not fields:
        return
    sets = ", ".join([f"{k}=:{k}" for k in fields.keys()])
    fields["wa"] = wa
    with get_session() as s:
        s.execute(text(f"UPDATE leads SET {sets}, last_contact=now() WHERE wa_number=:wa"), fields)
        s.commit()

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
    if not lead.get("name"):
        # Try to capture a name on the first reply
        if msg:
            # save anything non-empty as name; you can add smarter validation later
            _lead_update(wa, name=msg)
            send_whatsapp_text(wa, INTEREST_PROMPT.format(name=msg.split()[0].title()))
            return
        send_whatsapp_text(wa, WELCOME)
        return

    # If they typed keywords, allow fast path
    lower = msg.lower()
    if any(k in lower for k in ["faq", "questions", "info", "help", "menu"]):
        send_whatsapp_text(wa, FAQ_MENU_TEXT + "\n\nReply 0 to go back.")
        return

    # Numeric menu handling
    if msg.isdigit():
        n = int(msg)
        if 1 <= n <= 3:
            choices = {1: "taster", 2: "group", 3: "private"}
            interest = choices[n]
            _lead_update(wa, interest=interest, status="new")
            send_whatsapp_text(
                wa,
                f"Awesome! I’ve noted your interest in {interest}.\n"
                "An instructor will contact you shortly to schedule. 🙌\n\n"
                "Meanwhile, would you like the FAQ menu? (Reply YES/NO)"
            )
            _notify_admin(f"📥 New lead: {lead.get('name') or wa} wants {interest}.")
            return
        if n == 4:
            send_whatsapp_text(wa, FAQ_MENU_TEXT + "\n\nReply 0 to go back.")
            return
        if n == 0:
            send_whatsapp_text(wa, INTEREST_PROMPT.format(name=lead.get("name", "there")))
            return

    # Quick YES/NO after interest capture
    if lower in ("yes", "y"):
        send_whatsapp_text(wa, FAQ_MENU_TEXT + "\n\nReply 0 to go back.")
        return
    if lower in ("no", "n"):
        send_whatsapp_text(wa, "No problem! If you change your mind, just say “FAQ” or a number 1–3 anytime.")
        return

    # If they reply with a number in FAQ menu
    if len(msg) == 1 and msg.isdigit():
        idx = int(msg) - 1
        if 0 <= idx < len(FAQ_ITEMS):
            title, answer = FAQ_ITEMS[idx]
            send_whatsapp_text(wa, f"*{title}*\n{answer}\n\nReply 0 for main menu.")
            return

    # Fallback: show interest menu again
    send_whatsapp_text(wa, INTEREST_PROMPT.format(name=lead.get("name", "there")))
