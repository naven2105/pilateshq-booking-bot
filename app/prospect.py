# app/prospect.py
from __future__ import annotations
import logging
from sqlalchemy import text
from .db import get_session
from .utils import send_whatsapp_text, normalize_wa
from .faqs import FAQ_ITEMS, FAQ_MENU_TEXT
from .config import NADINE_WA

# ───────────────────────────────────────────────
# Prompts
# ───────────────────────────────────────────────
WELCOME = (
    "Hi! 👋 I’m PilatesHQ’s assistant.\n"
    "Before we continue, may I have your *first name*?"
)

INTEREST_PROMPT = (
    "Hi {name}, thanks for your enquiry! Nadine has received your details and will contact you very soon. 🙌\n\n"
    "Meanwhile, would you like to:\n"
    "1) Learn more about PilatesHQ\n"
    "2) Book a session\n\n"
    "Reply with 1–2."
)

# ───────────────────────────────────────────────
# DB helpers
# ───────────────────────────────────────────────
def _lead_get_or_create(wa: str):
    with get_session() as s:
        row = s.execute(
            text("SELECT id, name, interest, status FROM leads WHERE wa_number=:wa"),
            {"wa": wa},
        ).mappings().first()
        if row:
            return dict(row)
        # brand new number
        s.execute(
            text("INSERT INTO leads (wa_number, status) VALUES (:wa, 'new') ON CONFLICT DO NOTHING"),
            {"wa": wa},
        )
        s.commit()
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
        s.commit()

def _notify_admin(text_msg: str):
    try:
        if NADINE_WA:
            send_whatsapp_text(normalize_wa(NADINE_WA), text_msg)
    except Exception:
        logging.exception("Failed to notify admin")

# ───────────────────────────────────────────────
# Main flow
# ───────────────────────────────────────────────
def start_or_resume(wa_number: str, incoming_text: str):
    """Entry point for unknown numbers from router."""
    wa = normalize_wa(wa_number)
    lead = _lead_get_or_create(wa)

    msg = (incoming_text or "").strip()

    # ── Step 1: If no name yet, *always* greet and request it
    if not lead.get("name"):
        if msg and lead.get("status") == "asked_name":
            # This is their reply after being asked → save it as name
            first_word = msg.split()[0].title()
            _lead_update(wa, name=first_word, status="named")
            send_whatsapp_text(wa, INTEREST_PROMPT.format(name=first_word))
            _notify_admin(f"📥 New lead: {first_word} has enquired.")
            return
        else:
            # First ever time → ask for name
            _lead_update(wa, status="asked_name")
            send_whatsapp_text(wa, WELCOME)
            return

    # ── Step 2: They already have a name → normal flow
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
            send_whatsapp_text(
                wa,
                "Awesome! Nadine will reach out shortly to schedule your session. 💜"
            )
            return
        if n == 0:
            send_whatsapp_text(wa, INTEREST_PROMPT.format(name=lead.get("name", "there")))
            return

    # fallback → re-show interest prompt
    send_whatsapp_text(wa, INTEREST_PROMPT.format(name=lead.get("name", "there")))
