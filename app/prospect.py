# app/prospect.py
from __future__ import annotations
import logging
from sqlalchemy import text
from .db import get_session
from .utils import send_whatsapp_text, normalize_wa
from .config import NADINE_WA
from . import admin_nudge

# ── Messages ─────────────────────────────────────────────
WELCOME = (
    "Hi! 👋 I’m PilatesHQ’s assistant.\n"
    "Before we continue, what’s your name?"
)

AFTER_NAME_MSG = (
    "Hi {name}, thanks for your enquiry! Nadine has received your details and will contact you very soon. 🙌\n\n"
    "🌐 In the meantime, you can learn more about us here: https://www.pilateshq.co.za"
)

CLIENT_MENU = (
    "💜 Welcome back, {name}!\n"
    "Here’s what I can help you with:\n\n"
    "1️⃣ View my bookings   → (or type *bookings*)\n"
    "2️⃣ Get my invoice     → (or type *invoice*)\n"
    "3️⃣ FAQs               → (or type *faq* or *questions*)\n"
    "0️⃣ Contact Nadine     → (or type *Nadine*)\n\n"
    "Please reply with a number or simple word."
)

# ── DB helpers ───────────────────────────────────────────
def _lead_get_or_create(wa: str):
    """Fetch or create a lead record by WhatsApp number."""
    with get_session() as s:
        row = s.execute(
            text("SELECT id, name FROM leads WHERE wa_number=:wa"),
            {"wa": wa},
        ).mappings().first()
        if row:
            return dict(row)

        s.execute(
            text("INSERT INTO leads (wa_number, created_at) VALUES (:wa, now()) ON CONFLICT DO NOTHING"),
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


def _client_get(wa: str):
    """Return client record if number exists in clients table."""
    with get_session() as s:
        row = s.execute(
            text("SELECT id, name FROM clients WHERE wa_number=:wa"),
            {"wa": wa},
        ).mappings().first()
        return dict(row) if row else None


# ── Main entry ──────────────────────────────────────────
def start_or_resume(wa_number: str, incoming_text: str):
    wa = normalize_wa(wa_number)
    client = _client_get(wa)
    msg = (incoming_text or "").strip()

    # ── Clients get client menu ──
    if client:
        send_whatsapp_text(wa, CLIENT_MENU.format(name=client.get("name", "there")))
        return

    # ── Prospects flow ──
    lead = _lead_get_or_create(wa)

    # Step 1: ask for name if not provided
    if not lead.get("name"):
        bad_inputs = {"hi", "hello", "hey", "test"}
        if not msg or msg.lower() in bad_inputs or len(msg) < 2:
            logging.info(f"[prospect] bad/empty input={msg!r}, sending welcome")
            send_whatsapp_text(wa, WELCOME)
            return

        _lead_update(wa, name=msg)
        try:
            admin_nudge.notify_new_lead(msg, wa)
        except Exception:
            logging.exception("Failed to send admin nudge for new lead")
        send_whatsapp_text(wa, AFTER_NAME_MSG.format(name=msg))
        return

    # Step 2: all future messages → same polite thank-you
    send_whatsapp_text(
        wa,
        AFTER_NAME_MSG.format(name=lead.get("name", "there"))
    )
