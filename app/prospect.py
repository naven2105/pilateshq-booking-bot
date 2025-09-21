# app/prospect.py
from __future__ import annotations
import logging
from sqlalchemy import text
from .db import get_session
from .utils import send_whatsapp_text, normalize_wa
from .faqs import FAQ_ITEMS, FAQ_MENU_TEXT
from .config import NADINE_WA

# ── Messages ─────────────────────────────────────────────
WELCOME = (
    "Hi! 👋 I’m PilatesHQ’s assistant.\n"
    "Before we continue, what’s your name?"
)

INTEREST_PROMPT = (
    "Hi {name}, thanks for your enquiry! Nadine has received your details and will contact you very soon. 🙌\n\n"
    "Meanwhile, would you like to:\n"
    "1) Book a session (Nadine will contact you)\n"
    "2) Learn more about PilatesHQ\n\n"
    "Reply with 1–2."
)

# ── DB helpers ───────────────────────────────────────────
def _lead_get_or_create(wa: str):
    with get_session() as s:
        row = s.execute(
            text("SELECT id, name, interest, status FROM leads WHERE wa_number=:wa"),
            {"wa": wa},
        ).mappings().first()
        if row:
            return dict(row)
        # brand new lead → insert awaiting_name
        s.execute(
            text("INSERT INTO leads (wa_number, status) VALUES (:wa, 'awaiting_name') ON CONFLICT DO NOTHING"),
            {"wa": wa},
        )
        return {"id": None, "name": None, "interest": None, "status": "awaiting_name"}


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

# ── Main entry ──────────────────────────────────────────
def start_or_resume(wa_number: str, incoming_text: str):
    """Entry point for unknown numbers from router."""
    wa = normalize_wa(wa_number)
    lead = _lead_get_or_create(wa)
    msg = (incoming_text or "").strip()

    # ── Step 1: ask for name until provided ──
    if not lead.get("name"):
        if lead.get("status") == "awaiting_name":
            # They replied after we asked → save as name
            _lead_update(wa, name=msg, status="named")
            _notify_admin(f"📥 New lead: {msg} (wa={wa})")
            send_whatsapp_text(wa, INTEREST_PROMPT.format(name=msg))
            return
        # Always request name first time
        _lead_update(wa, status="awaiting_name")
        send_whatsapp_text(wa, WELCOME)
        return

    # ── Step 2: menu navigation ──
    lower = msg.lower()
    if msg == "1":
        send_whatsapp_text(
            wa,
            "Great! Nadine will contact you directly to arrange your booking. 💜"
        )
        return
    if msg == "2":
        send_whatsapp_text(wa, FAQ_MENU_TEXT + "\n\nReply 0 to go back.")
        return
    if msg == "0":
        send_whatsapp_text(wa, INTEREST_PROMPT.format(name=lead.get("name", "there")))
        return

    # fallback → repeat menu
    send_whatsapp_text(wa, INTEREST_PROMPT.format(name=lead.get("name", "there")))
