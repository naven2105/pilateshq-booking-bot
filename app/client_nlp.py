# app/client_nlp.py
"""
Lightweight natural-language parsing for client shortcuts.
Supports:
  - View bookings: "show my bookings", "when is my next session?"
  - Get invoice: "send me my invoice", "I need a statement"
  - FAQs: "questions", "faq", "what do you offer"
  - Contact Nadine: "speak to Nadine", "call me", "contact instructor"
"""

import re

def parse_client_command(text: str) -> dict | None:
    if not text:
        return None

    s = text.strip().lower()

    # Bookings
    if re.search(r"\b(bookings?|sessions?|schedule|next session)\b", s):
        return {"intent": "show_bookings"}

    # Invoices
    if re.search(r"\b(invoice|statement|payment|bill)\b", s):
        return {"intent": "get_invoice"}

    # FAQs
    if re.search(r"\b(faq|question|help|info|information|offer)\b", s):
        return {"intent": "faq"}

    # Contact Nadine / Admin
    if re.search(r"\b(contact|speak|call|whatsapp|talk).*(nadine|instructor|admin)?\b", s):
        return {"intent": "contact_admin"}

    return None
