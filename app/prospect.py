# app/prospect.py
from __future__ import annotations
import logging
from datetime import datetime
from sqlalchemy import text
from .db import get_session
from .utils import send_whatsapp_text, normalize_wa
from .config import NADINE_WA

# ── Messages ─────────────────────────────────────────────
WELCOME = (
    "Hi! 👋 I’m PilatesHQ’s assistant.\n"
    "Before we continue, what’s your name?"
)

AFTER_NAME_MSG = (
    "Hi {name}, thanks for your enquiry! Nadine has received your details and will contact you very soon. 🙌\n\n"
    "🌐 In the meantime, you can learn more about us here: https://www.pilateshq.co.za"
)

REENGAGED_MSG = (
    "Hi {name}, welcome back! Nadine will follow up with you shortly. 🙌\n\n"
    "🌐 In the meantime, you can explore more here: https://www.pilateshq.co.za"
)

CLIENT_MENU = (
    "💜 Welcome back, {name}!\n"
    "Here’s what I can help you with:\n\n"
    "1️⃣ Book a session\n"
    "2️⃣ View my bookings\n"
    "3️⃣ Get my invoice\n"
    "4️⃣ FAQs\n\n"
    "Please reply with a number to continue."
)


# ── DB helpers ───────────────────────────────────────────
def _lead_get(wa: str):
    with get_session() as s:
        row = s.execute(
            text("SELECT id, name FROM leads WHERE wa_number=:wa"),
            {"wa": wa},
        ).mappings().first()
        return dict(row) if row else None


def _lead_insert(wa: str):
    with get_session() as s:
        s.execute(
            text("INSERT INTO leads (wa_number) VALUES (:wa) ON CONFLICT DO NOTHING"),
            {"wa": wa},
        )


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
    with get_session() as s:
        row = s.execute(
            text("SELECT id, name FROM clients WHERE wa_number=:wa"),
            {"wa": wa},
        ).mappings().first()
        return dict(row) if row else None


def _notify_admin_new(name: str | None, wa: str):
    try:
        if not NADINE_WA:
            return
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        msg = (
            "📌 *New Lead Captured*\n"
            f"👤 Name: {name or '(not provided)'}\n"
            f"📱 WhatsApp: {wa}\n"
            f"🕒 Time: {ts}"
        )
        send_whatsapp_text(normalize_wa(NADINE_WA), msg)
    except Exception:
        logging.exception("Failed to notify admin of new lead")


def _notify_admin_reengaged(name: str | None, wa: str):
    try:
        if not NADINE_WA:
            return
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        msg = (
            "🔄 *Lead Re-engaged*\n"
            f"👤 Name: {name or '(not provided)'}\n"
            f"📱 WhatsApp: {wa}\n"
            f"🕒 Time: {ts}"
        )
        send_whatsapp_text(normalize_wa(NADINE_WA), msg)
    except Exception:
        logging.exception("Failed to notify admin of re-engaged lead")


# ── Main entry ──────────────────────────────────────────
def start_or_resume(wa_number: str, incoming_text: str):
    """Entry point for unknown numbers from router."""
    wa = normalize_wa(wa_number)
    msg = (incoming_text or "").strip()

    # Case 1: Already a client → route to client services
    client = _client_get(wa)
    if client:
        send_whatsapp_text(wa, CLIENT_MENU.format(name=client.get("name", "there")))
        return

    # Case 2: Not in leads yet → new prospect
    lead = _lead_get(wa)
    if not lead:
        _lead_insert(wa)
        _lead_update(wa, name=msg)
        _notify_admin_new(msg, wa)
        send_whatsapp_text(wa, AFTER_NAME_MSG.format(name=msg))
        return

    # Case 3: Lead exists but not converted → re-engaged
    if lead.get("name"):
        _lead_update(wa)  # just update last_contact timestamp
        _notify_admin_reengaged(lead.get("name"), wa)
        send_whatsapp_text(wa, REENGAGED_MSG.format(name=lead.get("name")))
        return

    # Case 4: Lead exists but no name captured yet → ask name
    if not lead.get("name"):
        _lead_update(wa, name=msg)
        _notify_admin_new(msg, wa)
        send_whatsapp_text(wa, AFTER_NAME_MSG.format(name=msg))
        return
