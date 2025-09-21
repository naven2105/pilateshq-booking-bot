# app/prospect.py
from __future__ import annotations
import logging
from sqlalchemy import text
from .db import get_session
from .utils import send_whatsapp_text, normalize_wa
from .faqs import FAQ_ITEMS, FAQ_MENU_TEXT
from .config import NADINE_WA

# ──────────────────────────────────────────────
# Messages
# ──────────────────────────────────────────────
WELCOME = (
    "Hi 👋 I’m PilatesHQ’s assistant.\n"
    "Before we continue, what’s your *name*?"
)

INTEREST_PROMPT = (
    "Hi {name}, thanks for your enquiry! Nadine has received your details "
    "and will contact you very soon. 🙌\n\n"
    "Meanwhile, would you like to:\n"
    "1) Book a session (Nadine will contact you)\n"
    "2) Learn more about PilatesHQ\n\n"
    "Reply with 1–2."
)

# ──────────────────────────────────────────────
# DB helpers
# ──────────────────────────────────────────────
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

# ──────────────────────────────────────────────
# Notifications
# ──────────────────────────────────────────────
def _notify_admin(text_msg: str):
    try:
        if NADINE_WA:
            send_whatsapp_text(normalize_wa(NADINE_WA), text_msg)
    except Exception:
        logging.exception("Failed to notify admin")

# ──────────────────────────────────────────────
# Flow entry
# ──────────────────────────────────────────────
def start_or_resume(wa_number: str, incoming_text: str):
    """Entry point for unknown numbers from router."""
    wa = normalize_wa(wa_number)
    lead = _lead_get_or_create(wa)

    msg = (incoming_text or "").strip()

    # STEP 1: If we don't have their name yet → always ask for it
    if not lead.get("name"):
        if msg:
            # Save full string as their name (not just first word)
            _lead_update(wa, name=msg)
            # Notify Nadine immediately with referral
            _notify_admin(f"📥 NEW LEAD: {msg} ({wa}) enquired via bot.")
            # Greet them and offer options
            send_whatsapp_text(wa, INTEREST_PROMPT.format(name=msg))
            return
        else:
            send_whatsapp_text(wa, WELCOME)
            return

    # STEP 2: Handle FAQs shortcut
    lower = msg.lower()
    if any(k in lower for k in ["faq", "questions", "info", "help", "menu"]):
        send_whatsapp_text(wa, FAQ_MENU_TEXT + "\n\nReply 0 to go back.")
        return

    # STEP 3: Handle numeric choices
    if msg.isdigit():
        n = int(msg)
        if n == 1:
            # Book a session → Nadine already has referral
            send_whatsapp_text(
                wa,
                "Perfect! Nadine will contact you directly to arrange your booking. 💜"
            )
            return
        if n == 2:
            send_whatsapp_text(wa, FAQ_MENU_TEXT + "\n\nReply 0 to go back.")
            return
        if n == 0:
            send_whatsapp_text(wa, INTEREST_PROMPT.format(name=lead.get("name", "there")))
            return

    # STEP 4: Fallback → capture as extra info and notify Nadine
    if msg:
        _lead_update(wa, interest=msg)
        _notify_admin(f"ℹ️ EXTRA INFO from {lead.get('name') or wa}: {msg}")
        send_whatsapp_text(
            wa,
            "Thanks for sharing that! Nadine will see this too. 💜\n\n"
            "Meanwhile, would you like to:\n"
            "1) Book a session (Nadine will contact you)\n"
            "2) Learn more about PilatesHQ"
        )
        return

    # Default: repeat menu
    send_whatsapp_text(wa, INTEREST_PROMPT.format(name=lead.get("name", "there")))
