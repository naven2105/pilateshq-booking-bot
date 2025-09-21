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
    "Before we continue, what’s your *name*?"
)

INTEREST_PROMPT = (
    "Hi {name}, thanks for your enquiry! Nadine has received your details and will contact you very soon. 🙌\n\n"
    "Meanwhile, would you like to:\n"
    "1) Book a session (Nadine will contact you)\n"
    "2) Learn more about PilatesHQ\n\n"
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


def _notify_admin_newlead(name: str, wa: str, interest: str | None = None):
    """Notify Nadine of a *new lead* when we first get the name."""
    if not NADINE_WA:
        return
    msg = f"📥 New lead: {name} ({wa})"
    if interest:
        msg += f" wants {interest}"
    send_whatsapp_text(normalize_wa(NADINE_WA), msg)


def _notify_admin_update(name: str, detail: str):
    """Notify Nadine when the same lead shares extra info later."""
    if not NADINE_WA:
        return
    msg = f"📥 Lead update – {name}: {detail}"
    send_whatsapp_text(normalize_wa(NADINE_WA), msg)


def start_or_resume(wa_number: str, incoming_text: str):
    """Entry point for unknown numbers from router."""
    wa = normalize_wa(wa_number)
    lead = _lead_get_or_create(wa)

    msg = (incoming_text or "").strip()

    # ── Always request name first if not known ──
    if not lead.get("name"):
        if msg:
            _lead_update(wa, name=msg)
            _notify_admin_newlead(msg, wa)  # notify Nadine right here
            send_whatsapp_text(wa, INTEREST_PROMPT.format(name=msg))
            return
        send_whatsapp_text(wa, WELCOME)
        return

    # ── Interpret menu responses ──
    lower = msg.lower()

    if msg == "1":
        _lead_update(wa, interest="book_session")
        _notify_admin_update(lead["name"], "Wants to book a session")
        send_whatsapp_text(
            wa,
            "Great! Nadine will contact you shortly to arrange your booking. 💜"
        )
        return

    if msg == "2":
        _lead_update(wa, interest="learn_more")
        _notify_admin_update(lead["name"], "Wants to learn more")
        send_whatsapp_text(wa, FAQ_MENU_TEXT + "\n\nReply 0 to go back.")
        return

    if msg == "0":
        send_whatsapp_text(wa, INTEREST_PROMPT.format(name=lead.get("name", "there")))
        return

    # Fallback → re-offer menu
    send_whatsapp_text(wa, INTEREST_PROMPT.format(name=lead.get("name", "there")))
