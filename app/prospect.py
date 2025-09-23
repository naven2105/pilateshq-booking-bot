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

        # brand new lead
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


# ── Notifications ───────────────────────────────────────
def _notify_admin_new_lead(name: str, wa: str):
    """Notify Nadine of a new prospect lead and log it."""
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    msg = (
        "📥 *New Prospect Lead*\n"
        f"• Name: {name}\n"
        f"• WhatsApp: {wa}\n"
        f"• Received: {ts}\n\n"
        "👉 To convert: reply `convert {wa}`\n"
        "👉 Or add with number: `add John with number 0821234567`"
    )
    try:
        if NADINE_WA:
            send_whatsapp_text(normalize_wa(NADINE_WA), msg)
        with get_session() as s:
            s.execute(
                text("INSERT INTO notifications_log (client_id, message, created_at) "
                     "VALUES (NULL, :msg, now())"),
                {"msg": msg},
            )
    except Exception:
        logging.exception("Failed to notify admin about new lead")


# ── Admin actions ───────────────────────────────────────
def handle_admin_reply(wa_number: str, text_in: str):
    """
    Handle Nadine’s replies like:
    - convert 2773...
    - add John with number 082...
    """
    wa = normalize_wa(wa_number)
    lower = (text_in or "").strip().lower()

    if lower.startswith("convert "):
        lead_wa = normalize_wa(text_in.split(" ", 1)[1])
        with get_session() as s:
            lead = s.execute(
                text("SELECT id, name FROM leads WHERE wa_number=:wa"),
                {"wa": lead_wa},
            ).mappings().first()
            if not lead:
                send_whatsapp_text(wa, f"⚠ No lead found with number {lead_wa}.")
                return
            s.execute(
                text("INSERT INTO clients (name, wa_number, phone, package_type) "
                     "VALUES (:n, :wa, :wa, 'manual') ON CONFLICT DO NOTHING"),
                {"n": lead["name"], "wa": lead_wa},
            )
            s.execute(
                text("UPDATE leads SET status='converted' WHERE wa_number=:wa"),
                {"wa": lead_wa},
            )
        send_whatsapp_text(wa, f"✅ Lead {lead['name']} ({lead_wa}) converted to client.")
        return

    if lower.startswith("add "):
        # crude parse: "add John with number 0821234567"
        parts = text_in.split("with number")
        if len(parts) == 2:
            name = parts[0].replace("add", "").strip()
            number = normalize_wa(parts[1].strip())
            with get_session() as s:
                s.execute(
                    text("INSERT INTO clients (name, wa_number, phone, package_type) "
                         "VALUES (:n, :wa, :wa, 'manual') ON CONFLICT DO NOTHING"),
                    {"n": name, "wa": number},
                )
            send_whatsapp_text(wa, f"✅ Client '{name}' added with number {number}.")
            return

    # fallback
    send_whatsapp_text(wa, "⚠ Unknown admin reply. Use `convert <wa>` or `add <name> with number <cell>`.")


# ── Main entry ──────────────────────────────────────────
def start_or_resume(wa_number: str, incoming_text: str):
    """
    Entry point for inbound messages.
    - If number exists in clients → show client menu.
    - If not, handle as a prospect (ask name → thank-you → polite repeat).
    """
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
        # ignore empty, emoji, or generic greetings as "names"
        bad_inputs = {"hi", "hello", "hey", "test"}
        if not msg or msg.lower() in bad_inputs or len(msg) < 2:
            send_whatsapp_text(wa, WELCOME)
            return

        _lead_update(wa, name=msg)
        _notify_admin_new_lead(msg, wa)
        send_whatsapp_text(wa, AFTER_NAME_MSG.format(name=msg))
        return

    # Step 2: all future messages → same polite thank-you
    send_whatsapp_text(
        wa,
        AFTER_NAME_MSG.format(name=lead.get("name", "there"))
    )
