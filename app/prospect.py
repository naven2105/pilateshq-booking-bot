# app/prospect.py
from __future__ import annotations
import logging
import re
from sqlalchemy import text
from .db import get_session
from .utils import send_whatsapp_text, normalize_wa
from .faqs import FAQ_MENU_TEXT  # FAQ_ITEMS not needed in this minimal flow
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

# ── Heuristics: what looks like a real name? ────────────────────────────────
_STOP_PHRASES = {
    "hi", "hello", "hey", "yo", "morning", "good morning", "good afternoon",
    "good evening", "hola", "howzit", "how are you", "test"
}
_EMOJI_ONLY_RE = re.compile(r"^\W+$")

def _looks_like_name(msg: str) -> bool:
    s = (msg or "").strip()
    if not s:
        return False
    # reject obvious non-names
    low = s.lower()
    if low in _STOP_PHRASES:
        return False
    if s.isdigit():
        return False
    if _EMOJI_ONLY_RE.match(s):
        return False
    # must contain at least one letter
    if not re.search(r"[A-Za-z]", s):
        return False
    # accept multi-word or typical name punctuation (apostrophes / hyphens)
    tokens = s.split()
    if len(tokens) >= 2:
        return True
    if "'" in s or "-" in s:
        return True
    # single short token (e.g., “Sam”)—accept if >= 3 letters and not a stop phrase
    letters = re.sub(r"[^A-Za-z]", "", s)
    return len(letters) >= 3

# ── DB helpers ───────────────────────────────────────────
def _get_existing_name_from_clients(wa: str) -> str | None:
    with get_session() as s:
        row = s.execute(
            text("SELECT name FROM clients WHERE wa_number=:wa LIMIT 1"),
            {"wa": wa},
        ).first()
        return row[0] if row and row[0] else None

def _get_existing_name_from_leads(wa: str) -> str | None:
    with get_session() as s:
        row = s.execute(
            text("SELECT name FROM leads WHERE wa_number=:wa LIMIT 1"),
            {"wa": wa},
        ).first()
        return row[0] if row and row[0] else None

def _ensure_lead_row(wa: str) -> None:
    with get_session() as s:
        s.execute(
            text("INSERT INTO leads (wa_number) VALUES (:wa) ON CONFLICT (wa_number) DO NOTHING"),
            {"wa": wa},
        )

def _save_lead_name(wa: str, name: str) -> None:
    with get_session() as s:
        s.execute(
            text("UPDATE leads SET name=:name, last_contact=now() WHERE wa_number=:wa"),
            {"name": name.strip(), "wa": wa},
        )

def _notify_admin(text_msg: str):
    try:
        if NADINE_WA:
            send_whatsapp_text(normalize_wa(NADINE_WA), text_msg)
    except Exception:
        logging.exception("Failed to notify admin")

# ── Main entry ──────────────────────────────────────────
def start_or_resume(wa_number: str, incoming_text: str):
    """
    For ANY new number:
      • If we don’t have a real name yet (in clients or leads), ALWAYS ask for it.
      • Only accept replies that look like a name (not hi/hello/1/emoji).
      • After saving a valid name → notify Nadine once and show the 1–2 menu.
    """
    wa = normalize_wa(wa_number)
    msg = (incoming_text or "").strip()

    # 1) If already a known client, use their name
    name = _get_existing_name_from_clients(wa)
    if not name:
        # 2) Ensure a leads row exists for this wa
        _ensure_lead_row(wa)
        # 3) Try leads name
        name = _get_existing_name_from_leads(wa)

    # 4) If we still don’t have a name, try to capture it from this message
    if not name:
        if _looks_like_name(msg):
            _save_lead_name(wa, msg)
            _notify_admin(f"📥 New lead: {msg} (wa={wa})")
            send_whatsapp_text(wa, INTEREST_PROMPT.format(name=msg))
            return
        # Not a valid name → (re)ask
        send_whatsapp_text(wa, WELCOME)
        return

    # 5) We have a name → proceed with simple menu
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
        send_whatsapp_text(wa, INTEREST_PROMPT.format(name=name))
        return

    # fallback → repeat menu
    send_whatsapp_text(wa, INTEREST_PROMPT.format(name=name))
