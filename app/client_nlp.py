# app/client_nlp.py
"""
Lightweight natural-language parsing for client shortcuts.
Supports:
  - View bookings: "show my bookings", "when is my next session?"
  - Cancel bookings: "cancel next", "cancel Tue 08h00"
  - Attendance updates: "I am sick", "cannot make it", "running late"
  - Get invoice: "send me my invoice", "I need a statement"
  - FAQs: "questions", "faq", "what do you offer"
  - Contact Nadine: "speak to Nadine", "call me", "contact instructor"
"""

import re
from datetime import datetime


def parse_client_command(text: str) -> dict | None:
    if not text:
        return None

    s = text.strip().lower()

    # ── Bookings ──
    if re.search(r"\b(bookings?|sessions?|schedule|next session)\b", s):
        return {"intent": "show_bookings"}

    # ── Cancel next session ──
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

    # ── Cannot attend / generic cancel ──
    if s in {"cannot make it", "cannot attend", "not coming", "skip"}:
        return {"intent": "cancel_today"}

    # ── Running late ──
    if "late" in s or "running late" in s:
        return {"intent": "running_late"}

    # ── Invoices ──
    if re.search(r"\b(invoice|statement|payment|bill)\b", s):
        month = datetime.now().strftime("%B %Y")
        return {"intent": "get_invoice", "month": month}

    # ── FAQs ──
    if re.search(r"\b(faq|question|help|info|information|offer)\b", s):
        return {"intent": "faq"}

    # ── Contact Nadine / Admin ──
    if re.search(r"\b(contact|speak|call|whatsapp|talk).*(nadine|instructor|admin)?\b", s):
        return {"intent": "contact_admin"}

    return None
