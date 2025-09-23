# app/admin_nlp.py
"""
Lightweight natural-language parsing for admin shortcuts.
Now supports:
  - Single-day bookings
  - Recurring bookings
  - Multi-day recurring bookings
Also integrates client promotion: if wa_number is passed, lead → client conversion occurs.
"""

import re
from datetime import datetime, timedelta

WEEKDAYS = {
    "mon":0,"monday":0,"tue":1,"tues":1,"tuesday":1,"wed":2,"wednesday":2,
    "thu":3,"thurs":3,"thursday":3,"fri":4,"friday":4,"sat":5,"saturday":5,"sun":6,"sunday":6
}
MONTHS = {
    "jan":1,"january":1,"feb":2,"february":2,"mar":3,"march":3,"apr":4,"april":4,"may":5,
    "jun":6,"june":6,"jul":7,"july":7,"aug":8,"august":8,"sep":9,"sept":9,"september":9,
    "oct":10,"october":10,"nov":11,"november":11,"dec":12,"december":12
}

# ────────────────────────────────────────────────
# Time parsing
# ────────────────────────────────────────────────
def parse_time_word(t: str) -> str | None:
    t = t.lower().strip()
    m = re.fullmatch(r'(\d{1,2})h(\d{2})', t)
    if m:
        return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"
    m = re.fullmatch(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)', t)
    if m:
        hh = int(m.group(1)); mm = int(m.group(2) or 0); ap = m.group(3)
        if ap == "pm" and hh != 12: hh += 12
        if ap == "am" and hh == 12: hh = 0
        return f"{hh:02d}:{mm:02d}"
    m = re.fullmatch(r'(\d{1,2}):(\d{2})', t)
    if m:
        return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"
    m = re.fullmatch(r'(\d{1,2})', t)
    if m:
        return f"{int(m.group(1)):02d}:00"
    return None

# ────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────
_SLOT_SINGLE_WORDS = {"single","solo","1-1","1:1","one-to-one","one2one"}
_SLOT_DUO_WORDS    = {"duo","couple","2-1","pair","partner"}

def _norm_slot_type(raw: str | None, has_partner: bool) -> str:
    if raw:
        r = raw.strip().lower()
        if r in _SLOT_SINGLE_WORDS: return "single"
        if r in _SLOT_DUO_WORDS:    return "duo"
    return "duo" if has_partner else "single"

def _weekday_from(s: str) -> int | None:
    return WEEKDAYS.get(s.strip().lower())

def _split_two_names(name_blob: str) -> tuple[str, str | None]:
    m = re.match(r'(.+?)\s+(?:and|&)\s+(.+)$', name_blob.strip(), flags=re.IGNORECASE)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return name_blob.strip(), None

# ────────────────────────────────────────────────
# Main booking parsers
# ────────────────────────────────────────────────
def parse_admin_command(text: str, wa_number: str | None = None) -> dict | None:
    """
    Returns dict with 'intent' and parameters.
    Includes wa_number so booking.py can auto-promote lead → client.
    """
    s = text.strip()

    # 1) Single booking
    m = re.match(r'(?i)^book\s+(.+?)\s+on\s+(\d{4}-\d{2}-\d{2})\s+([0-9:apmh]+|[0-2]?\dh[0-5]\d)(?:\s+(single|duo|couple))?(?:\s+(?:with)\s+(.+))?$', s)
    if m:
        name_blob, dstr, timestr, type_word, partner = m.groups()
        name, inferred_partner = _split_two_names(name_blob)
        hhmm = parse_time_word(timestr)
        if not hhmm: return None
        has_partner = bool(partner or inferred_partner)
        slot_type = _norm_slot_type(type_word, has_partner)
        return {
            "intent": "book_single",
            "name": name,
            "date": dstr,
            "time": hhmm,
            "slot_type": slot_type,
            "partner": (partner or inferred_partner),
            "wa_number": wa_number,
        }

    # 2) Recurring (single weekday)
    m = re.match(r'(?i)^book\s+(.+?)\s+every\s+([a-z]+)\s+([0-9:apmh]+|[0-2]?\dh[0-5]\d)(?:\s+(single|duo|couple))?$', s)
    if m:
        name_blob, wday, timestr, type_word = m.groups()
        if _weekday_from(wday) is None: return None
        name, partner = _split_two_names(name_blob)
        hhmm = parse_time_word(timestr)
        if not hhmm: return None
        slot_type = _norm_slot_type(type_word, bool(partner))
        return {
            "intent": "book_recurring",
            "name": name,
            "weekday": _weekday_from(wday),
            "time": hhmm,
            "slot_type": slot_type,
            "partner": partner,
            "until_cancelled": True,
            "wa_number": wa_number,
        }

    # 3) Recurring multi-day
    m = re.match(r'(?i)^book\s+(.+?)\s+every\s+(.+)$', s)
    if m:
        name_blob, rest = m.groups()
        name, partner = _split_two_names(name_blob)
        segments = re.split(r'(?i)\s+and\s+', rest.strip())
        slots = []
        for seg in segments:
            ms = re.match(r'(?i)^([a-z]+)\s+([0-9:apmh]+|[0-2]?\dh[0-5]\d)(?:\s+(single|duo|couple))?$', seg.strip())
            if not ms: return None
            wday, timestr, type_word = ms.groups()
            wdi = _weekday_from(wday)
            if wdi is None: return None
            hhmm = parse_time_word(timestr)
            if not hhmm: return None
            slot_type = _norm_slot_type(type_word, bool(partner))
            slots.append({"weekday": wdi, "time": hhmm, "slot_type": slot_type, "partner": partner if slot_type=="duo" else None})
        return {"intent": "book_recurring_multi", "name": name, "slots": slots, "until_cancelled": True, "wa_number": wa_number}

    # 4) Tomorrow helper
    m = re.match(r'(?i)^book\s+(.+?)\s+tomorrow\s+([0-9:apmh]+|[0-2]?\dh[0-5]\d)(?:\s+(single|duo|couple))?$', s)
    if m:
        name_blob, timestr, type_word = m.groups()
        name, partner = _split_two_names(name_blob)
        hhmm = parse_time_word(timestr)
        if not hhmm: return None
        tomorrow = (datetime.utcnow() + timedelta(days=1)).date().isoformat()
        slot_type = _norm_slot_type(type_word, bool(partner_
