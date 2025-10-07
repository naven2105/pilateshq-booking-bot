"""
client_nlp.py
──────────────
Lightweight natural-language parsing for client shortcuts.
Supports:
  - View bookings
  - Cancel bookings (next / by date & time)
  - Attendance updates (sick, cancel today, running late)
  - Invoices
  - FAQs / Menu
  - Contact Nadine
"""

import re


def parse_client_command(text: str) -> dict | None:
    if not text:
        return None

    s = text.strip().lower()

    # ── Menu ──
    if s in {"menu", "help"}:
        return {"intent": "menu"}

    # ── Bookings ──
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

    # ── Sick today ──
    if s in {"i am sick", "sick", "not well"}:
        return {"intent": "off_sick_today"}

    # ── Cannot attend ──
    if s in {"cannot make it", "cannot attend", "not coming", "skip"}:
        return {"intent": "cancel_today"}

    # ── Running late ──
    if "late" in s or "running late" in s:
        return {"intent": "running_late"}

    # ── Invoices ──
    if re.search(r"\b(invoice|statement|payment|bill)\b", s):
        return {"intent": "get_invoice"}

    # ── FAQs ──
    if re.search(r"\b(faq|question|info|information|offer)\b", s):
        return {"intent": "faq"}

    # ── Contact Nadine ──
    if re.search(r"\b(contact|speak|call|whatsapp|talk).*(nadine|instructor|admin)?\b", s):
        return {"intent": "contact_admin"}

    return None
