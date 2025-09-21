# app/prospect.py
from __future__ import annotations
import logging
from sqlalchemy import text
from .db import get_session
from .utils import send_whatsapp_text, normalize_wa
from .faqs import FAQ_ITEMS, FAQ_MENU_TEXT
from .config import NADINE_WA

log = logging.getLogger(__name__)

WELCOME = (
    "Hi 👋 I’m PilatesHQ’s assistant.\n"
    "Before we continue, what’s your name?"
)

MENU_PROMPT = (
    "Meanwhile, would you like to:\n"
    "1) Book a session (Nadine will contact you)\n"
    "2) Learn more about PilatesHQ\n\n"
    "Reply with 1–2."
)


# ─────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────
def _lead_get_or_create(wa: str):
    with get_session() as s:
        row = s.execute(
            text("SELECT id, name, interest, status FROM leads WHERE wa_number=:wa"),
            {"wa": wa},
        ).mappings().first()
        if row:
            return dict(row)
        s.execute(
            text("INSERT INTO leads (wa_number, status) VALUES (:wa, 'new') "
                 "ON CONFLICT DO NOTHING"),
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


# ─────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────
def start_or_resume(wa_number: str, incoming_text: str):
    """Entry point for unknown numbers from router."""
    wa = normalize_wa(wa_number)
    lead = _lead_get_or_create(wa)

    msg = (incoming_text or "").strip()

    # ── Case 1: No name stored yet → always ask for name first
    if not lead.get("name"):
        if not msg:  # blank or emoji etc → re-ask
            send_whatsapp_text(wa, WELCOME)
            return

        # This is the *first meaningful reply*, treat it as their name
        name_clean = msg.strip().title()
        _lead_update(wa, name=name_clean)

        # Greet + Nadine referral
        send_whatsapp_text(
            wa,
            f"Hi {name_clean}, thanks for your enquiry! "
            "Nadine has received your details and will contact you very soon. 🙌"
        )

        # Offer menu right after
        send_whatsapp_text(wa, MENU_PROMPT)

        # Notify Nadine
        _notify_admin(f"📥 New lead: {name_clean} ({wa})")
        return

    # ── Case 2: Already has name → continue with menu logic
    lower = msg.lower()

    if msg == "1":
        _lead_update(wa, interest="session")
        send_whatsapp_text(
            wa,
            "Perfect 👍 Nadine will reach out shortly to arrange your booking."
        )
        return

    if msg == "2":
        send_whatsapp_text(wa, FAQ_MENU_TEXT + "\n\nReply 0 to go back.")
        return

    if msg == "0":
        send_whatsapp_text(wa, MENU_PROMPT)
        return

    if any(k in lower for k in ["faq", "info", "help"]):
        send_whatsapp_text(wa, FAQ_MENU_TEXT + "\n\nReply 0 to go back.")
        return

    # Fallback → re-show menu
    send_whatsapp_text(wa, MENU_PROMPT)
