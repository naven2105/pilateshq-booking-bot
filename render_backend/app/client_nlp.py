"""
client_nlp.py – Phase 20
───────────────────────────────
Lightweight natural-language parsing for client shortcuts.

Recognises:
  • View / cancel bookings
  • Attendance updates (sick, running late, cancel today)
  • Invoices / payments
  • Reschedule requests
  • FAQs and general help
  • Contact Nadine (admin)
  • Group availability lookup 🆕
  • Greetings
"""

import re
import logging

log = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────
# Simple keyword mappings (exact text matches)
# ────────────────────────────────────────────────────────────────
SIMPLE_INTENTS = {
    ("menu", "help"): "menu",
    ("sick", "not well", "i am sick"): "off_sick_today",
    ("skip", "cannot make it", "cannot attend", "not coming"): "cancel_today",
}

# ────────────────────────────────────────────────────────────────
# Core NLP function
# ────────────────────────────────────────────────────────────────
def parse_client_command(text: str) -> dict | None:
    if not text:
        return None

    s = text.strip().lower()

    # ── Greetings ──
    if re.fullmatch(r"(hi|hello|hey|morning|good morning|good afternoon|evening)", s):
        return {"intent": "greeting"}

    # ── Simple intent lookups ──
    for keys, intent in SIMPLE_INTENTS.items():
        if s in keys:
            return {"intent": intent}

    # ── Booking info ──
    if re.search(r"\b(bookings?|sessions?|schedule|next session)\b", s):
        return {"intent": "show_bookings"}

    # ── Cancel next ──
    if re.fullmatch(r"(cancel next|next cancel|cancel my next)", s):
        return {"intent": "cancel_next"}

    # ── Cancel by explicit day/time ──
    m = re.match(r"cancel\s+(?P<day>\w+)\s+(?P<time>[0-9:apmh]+|[0-2]?\dh[0-5]\d)", s)
    if m:
        return {
            "intent": "cancel_specific",
            "day": m.group("day"),
            "time": m.group("time"),
        }

    # ── Running late ──
    if "late" in s or "running late" in s:
        return {"intent": "running_late"}

    # ── Reschedule ──
    if "reschedule" in s or "move" in s:
        return {"intent": "reschedule_request"}

    # ── Payment confirmations ──
    if re.search(r"\b(paid|payment done|eft|proof sent|pop)\b", s):
        return {"intent": "payment_confirmation"}

    # ── Invoices ──
    if re.search(r"\b(invoice|statement|payment|bill)\b", s):
        return {"intent": "get_invoice"}

    # ── Group availability lookup 🆕 ──
    if re.search(r"\b(groups?|availability|group spaces?|open slots?|reformer slots?)\b", s):
        return {"intent": "group_availability"}

    # ── FAQs ──
    if re.search(r"\b(faq|question|info|information|offer|help)\b", s):
        return {"intent": "faq"}

    # ── Contact Nadine ──
    if re.search(r"\b(contact|speak|call|whatsapp|talk).*(nadine|instructor|admin)?\b", s):
        return {"intent": "contact_admin"}

    # ── Fallback ──
    log.debug(f"[client_nlp] Unmatched message: {text!r}")
    return None
