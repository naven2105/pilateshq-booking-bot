"""
Lightweight natural-language parsing for admin shortcuts.
Supports:
  - Single-day bookings
  - Recurring bookings (single and multi-day)
  - Client management (add client, update DOB, notes)
  - Attendance updates (sick, no-show, cancel next session)
  - Client deactivate flow (deactivate, confirm deactivate, cancel)
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

    # (existing booking parsing unchanged...)

    # Tomorrow helper
    m = re.match(
        r'(?i)^\s*book\s+(.+?)\s+tomorrow\s+([0-9:apmh]+|[0-2]?\dh[0-5]\d)'
        r'(?:\s+(single|solo|1-1|duo|couple))?\s*$',
        s,
    )
    if m:
        name_blob, timestr, type_word = m.groups()
        name, partner = _split_two_names(name_blob)
        hhmm = parse_time_word(timestr)
        if not hhmm:
            return None
        tomorrow = (datetime.utcnow() + timedelta(days=1)).date().isoformat()
        slot_type = _norm_slot_type(type_word, bool(partner))
        return {
            "intent": "book_single",
            "name": name,
            "date": tomorrow,
            "time": hhmm,
            "slot_type": slot_type,
            "partner": partner,
        }

    return None

# ──────────────────────────────────────────────────────────────────────────────
# Client & attendance commands
# ──────────────────────────────────────────────────────────────────────────────
def parse_admin_client_command(text: str) -> dict | None:
    s = text.strip()

    # ── Recurring booking (book_client) ──
    m = re.match(
        r'(?i)^\s*book\s+(?P<name>[A-Za-z\s]+)\s+(?P<session_type>\w+)\s+(?P<day>\w+)\s+(?P<time>[0-9:apmh]+|[0-2]?\dh[0-5]\d)(?:\s+dob=(?P<dob>[\d-]+))?(?:\s+health=(?P<health>.+))?',
        s,
    )
    if m:
        hhmm = parse_time_word(m.group("time"))
        return {
            "intent": "book_client",
            "name": m.group("name").strip(),
            "session_type": m.group("session_type").lower(),
            "day": m.group("day"),
            "time": hhmm,
            "dob": m.group("dob"),
            "health": m.group("health"),
        }

    # ── Add client ──
    m = re.match(r'(?i)^\s*add client\s+(.+?)\s+.*?(\+?\d+)\s*$', s)
    if m:
        return {"intent": "add_client", "name": m.group(1).strip(), "number": m.group(2)}

    # ── Update DOB ──
    m = re.match(r'(?i)^\s*update\s+dob\s+(.+?)\s+(\S+)\s*$', s)
    if m:
        return {"intent": "update_dob", "name": m.group(1).strip(), "dob": m.group(2)}

    # ── Cancel Next ──
    m = re.match(r'(?i)^\s*cancel\s+(.+?)\s*$', s)
    if m:
        return {"intent": "cancel_next", "name": m.group(1).strip()}

    # ── Sick ──
    m = re.match(r'(?i)^\s*sick\s+(.+?)\s*$', s)
    if m:
        return {"intent": "off_sick_today", "name": m.group(1).strip()}

    # ── No-show ──
    m = re.match(r'(?i)^\s*no-?show\s+(.+?)\s*$', s)
    if m:
        return {"intent": "no_show_today", "name": m.group(1).strip()}

    # ── Deactivation ──
    m = re.match(r'(?i)^\s*deactivate\s+(.+?)\s*$', s)
    if m:
        return {"intent": "deactivate", "name": m.group(1).strip()}

    m = re.match(r'(?i)^\s*confirm\s+deactivate\s+(.+?)\s*$', s)
    if m:
        return {"intent": "confirm_deactivate", "name": m.group(1).strip()}

    if s.lower() == "cancel":
        return {"intent": "cancel"}

    return None
