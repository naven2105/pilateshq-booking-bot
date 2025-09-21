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

MAIN_PROMPT = (
    "Hi {name}, thanks for your enquiry! Nadine has received your details and will contact you very soon. 🙌\n\n"
    "Meanwhile, would you like to:\n"
    "1) Tell us a bit more about you (optional)\n"
    "2) Learn more about PilatesHQ\n\n"
    "Reply with 1–2."
)

DETAILS_PROMPT = (
    "Thanks for sharing, {name}! 💜\n"
    "If you’d like, you can tell us:\n"
    "• Do you have any medical conditions or injuries we should know about?\n"
    "• Do you prefer group or private sessions?\n"
    "• How did you hear about PilatesHQ?\n\n"
    "You can answer in free text, or reply 0 to go back to the main menu."
)

# ── DB helpers ───────────────────────────────────────────
def _lead_get_or_create(wa: str):
    with get_session() as s:
        row = s.execute(
            text("SELECT id, name FROM leads WHERE wa_number=:wa"),
            {"wa": wa},
        ).mappings().first()

        if row:
            return dict(row)

        # brand new lead
        s.execute(
            text("INSERT INTO leads (wa_number) VALUES (:wa) ON CONFLICT DO NOTHING"),
            {"wa": wa},
        )
        return {"id": None, "name": None}


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
        if msg:
            # save this as their name
            _lead_update(wa, name=msg)
            _notify_admin(f"📥 New lead: {msg} (wa={wa})")
            send_whatsapp_text(wa, MAIN_PROMPT.format(name=msg))
            return
        else:
            send_whatsapp_text(wa, WELCOME)
            return

    # ── Step 2: menu navigation ──
    lower = msg.lower()
    if msg == "1":
        send_whatsapp_text(wa, DETAILS_PROMPT.format(name=lead.get("name", "there")))
        return
    if msg == "2":
        send_whatsapp_text(wa, FAQ_MENU_TEXT + "\n\nReply 0 to go back.")
        return
    if msg == "0":
        send_whatsapp_text(wa, MAIN_PROMPT.format(name=lead.get("name", "there")))
        return

    # ── Step 3: free-text details capture ──
    if lower not in {"1", "2"} and lead.get("name"):
        # treat this as optional extra details
        _lead_update(wa, interest=msg)
        _notify_admin(f"ℹ️ Extra info from {lead.get('name')}: {msg}")
        send_whatsapp_text(
            wa,
            "Thanks for sharing! Nadine will review this when she contacts you. 💜\n\n"
            "Reply 0 to return to the main menu."
        )
        return

    # fallback → repeat menu
    send_whatsapp_text(wa, MAIN_PROMPT.format(name=lead.get("name", "there")))
