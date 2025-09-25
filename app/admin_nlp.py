# app/admin_nlp.py
"""
Lightweight natural-language parsing for admin shortcuts.
Supports:
  - Single-day bookings
  - Recurring bookings (single and multi-day)
  - Client management (add client, update DOB, notes, deactivate)
  - Attendance updates (sick, no-show, cancel next session)
"""

import re
from datetime import datetime, timedelta

# ──────────────────────────────────────────────────────────────────────────────
# Dictionaries
# ──────────────────────────────────────────────────────────────────────────────
WEEKDAYS = {
    "mon": 0, "monday": 0,
    "tue": 1, "tues": 1, "tuesday": 1,
    "wed": 2, "wednesday": 2,
    "thu": 3, "thurs": 3, "thursday": 3,
    "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5,
    "sun": 6, "sunday": 6,
}
MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

# ──────────────────────────────────────────────────────────────────────────────
# Time parsing
# ──────────────────────────────────────────────────────────────────────────────
def parse_time_word(t: str) -> str | None:
    """Accepts times like '8', '8:30', '8am', '20:00', '08h30' → 'HH:MM'."""
    t = t.lower().strip()
    m = re.fullmatch(r'(\d{1,2})h(\d{2})', t)
    if m:
        return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"
    m = re.fullmatch(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)', t)
    if m:
        hh = int(m.group(1))
        mm = int(m.group(2) or 0)
        ap = m.group(3)
        if ap == "pm" and hh != 12:
            hh += 12
        if ap == "am" and hh == 12:
            hh = 0
        return f"{hh:02d}:{mm:02d}"
    m = re.fullmatch(r'(\d{1,2}):(\d{2})', t)
    if m:
        return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"
    m = re.fullmatch(r'(\d{1,2})', t)
    if m:
        return f"{int(m.group(1)):02d}:00"
    return None

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
_SLOT_SINGLE_WORDS = {"single", "solo", "1-1", "1:1", "one-to-one", "one2one"}
_SLOT_DUO_WORDS = {"duo", "couple", "2-1", "pair", "partner"}

def _norm_slot_type(raw: str | None, has_partner: bool) -> str:
    if raw:
        r = raw.strip().lower()
        if r in _SLOT_SINGLE_WORDS:
            return "single"
        if r in _SLOT_DUO_WORDS:
            return "duo"
    return "duo" if has_partner else "single"

def _weekday_from(s: str) -> int | None:
    return WEEKDAYS.get(s.strip().lower())

def _split_two_names(name_blob: str) -> tuple[str, str | None]:
    """Split 'Mary and John' → ('Mary', 'John')."""
    s = name_blob.strip()
    m = re.match(r'(.+?)\s+(?:and|&)\s+(.+)$', s, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return s, None

# ──────────────────────────────────────────────────────────────────────────────
# Booking commands
# ──────────────────────────────────────────────────────────────────────────────
def parse_admin_command(text: str) -> dict | None:
    s = text.strip()

    # (Existing booking parsing unchanged)
    # ...

    return None

# ──────────────────────────────────────────────────────────────────────────────
# Client & attendance commands
# ──────────────────────────────────────────────────────────────────────────────
def parse_admin_client_command(text: str) -> dict | None:
    s = text.strip()

    # Add client
    m = re.match(
        r'(?i)^\s*add\s+(?:new\s+)?client\s+(.+?)\s+(?:with\s+)?number\s+([+\d\s-]+)\s*$',
        s,
    )
    if m:
        import re as _re
        name = m.group(1).strip()
        number = _re.sub(r'\s|-', '', m.group(2))
        return {"intent": "add_client", "name": name, "number": number}

    # Update DOB
    m = re.match(r'(?i)^\s*change\s+(.+?)\s+date\s+of\s+birth\s+to\s+(\d{1,2})\s+([A-Za-z]+)\s*$', s)
    if m:
        name = m.group(1).strip()
        day = int(m.group(2))
        mon_raw = m.group(3).lower()
        month = MONTHS.get(mon_raw)
        if not month:
            return None
        return {"intent": "update_dob", "name": name, "day": day, "month": month}

    # Update medical/notes
    m = re.match(r'(?i)^\s*update\s+(.+?)\s*-\s*(.+)\s*$', s)
    if m:
        return {"intent": "update_medical", "name": m.group(1).strip(), "note": m.group(2).strip()}

    # Cancel next session
    m = re.match(r'(?i)^\s*cancel\s+(.+?)\s+next\s+session\s*$', s)
    if m:
        return {"intent": "cancel_next", "name": m.group(1).strip()}

    # Off sick today
    m = re.match(r'(?i)^\s*(.+?)\s+is\s+off\s+sick\.?\s*$', s)
    if m:
        return {"intent": "off_sick_today", "name": m.group(1).strip()}

    # No show today
    m = re.match(r'(?i)^\s*(.+?)\s+is\s+no\s+show\s+today\.?\s*$', s)
    if m:
        return {"intent": "no_show_today", "name": m.group(1).strip()}

    # 🔴 NEW: Deactivate client
    m = re.match(r'(?i)^\s*deactivate\s+(.+?)\s*$', s)
    if m:
        return {"intent": "deactivate", "name": m.group(1).strip()}

    # 🔴 NEW: Confirm deactivation
    m = re.match(r'(?i)^\s*confirm\s+deactivate\s+(.+?)\s*$', s)
    if m:
        return {"intent": "confirm_deactivate", "name": m.group(1).strip()}

    # 🔴 NEW: Cancel deactivation
    if s.lower().strip() == "cancel":
        return {"intent": "cancel"}

    return None
