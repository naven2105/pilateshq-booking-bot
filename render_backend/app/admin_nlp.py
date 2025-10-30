"""
admin_nlp.py – Phase 22c
────────────────────────────────────────────
Lightweight natural-language parser for Nadine’s WhatsApp commands.

Supports:
 • Add Tom Ford 0834566789
 • Update DOB Tom Ford 21-May
 • Update Notes Tom Ford prefers mornings
 • Update Email Tom Ford tom@example.com
 • Find Tom Ford
────────────────────────────────────────────
"""

import re


def parse_admin_client_command(text: str) -> dict | None:
    """Parse all client-related admin commands."""
    if not text:
        return None
    s = text.strip()

    # ── Add client ─────────────────────────────────────────────
    m = re.match(r"(?i)^add\s+([A-Za-z ]+)\s+(\d{9,13})$", s)
    if m:
        return {
            "intent": "add_client",
            "name": m.group(1).strip(),
            "number": m.group(2).strip(),
        }

    # ── Update DOB ─────────────────────────────────────────────
    # Example: "Update DOB Mary Smith 21-May"
    m = re.match(r"(?i)^update\s+dob\s+([A-Za-z ]+)\s+(\d{1,2}[-/ ]?[A-Za-z]{3,9})$", s)
    if m:
        return {
            "intent": "update_dob",
            "name": m.group(1).strip(),
            "dob": m.group(2).strip(),
        }

    # ── Update Notes ───────────────────────────────────────────
    # Example: "Update Notes Mary Smith prefers mornings"
    m = re.match(r"(?i)^update\s+notes\s+([A-Za-z ]+)\s+(.+)$", s)
    if m:
        return {
            "intent": "update_notes",
            "name": m.group(1).strip(),
            "notes": m.group(2).strip(),
        }

    # ── Update Email ───────────────────────────────────────────
    # Example: "Update Email Mary Smith mary@example.com"
    m = re.match(r"(?i)^update\s+email\s+([A-Za-z ]+)\s+([\w\.-]+@[\w\.-]+)$", s)
    if m:
        return {
            "intent": "update_email",
            "name": m.group(1).strip(),
            "email": m.group(2).strip(),
        }

    # ── Find Client ────────────────────────────────────────────
    # Example: "Find Mary Smith"
    m = re.match(r"(?i)^find\s+([A-Za-z ]+)$", s)
    if m:
        return {
            "intent": "find_client",
            "name": m.group(1).strip(),
        }

    # ── No match ───────────────────────────────────────────────
    return None
