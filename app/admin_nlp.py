# app/admin_nlp.py
"""
Lightweight natural-language parsing for admin shortcuts.
Now supports:
  - Single-day bookings:
      "Book Mary on 2025-09-01 08:00 single"
  - Recurring single day:
      "Book Mary every Tuesday 09h00 duo"
  - Recurring multi-day (mixed slot types):
      "Book Mary and John every Tuesday 09h00 and Thursday 10h00 single"
      "Book Sarah every Mon 07:30 duo and Wed 09:00 single"
Behavior:
  - If two names are given after 'Book', first is primary client; second is treated as duo partner by default.
  - Each segment may include an explicit slot type: single | 1-1 | solo | duo | couple.
  - If a partner is present and no explicit type is given for a segment, that segment defaults to 'duo'.
  - If no partner and no explicit type, defaults to 'single'.
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

# ──────────────────────────────────────────────────────────────────────────────
# Time parsing
# ──────────────────────────────────────────────────────────────────────────────
def parse_time_word(t: str) -> str | None:
    """
    Accepts times like '8', '8:30', '8am', '20:00', or '08h30' and returns 'HH:MM'.
    """
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

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
_SLOT_SINGLE_WORDS = {"single","solo","1-1","1:1","one-to-one","one2one"}
_SLOT_DUO_WORDS    = {"duo","couple","2-1","pair","partner"}

def _norm_slot_type(raw: str | None, has_partner: bool) -> str:
    if raw:
        r = raw.strip().lower()
        if r in _SLOT_SINGLE_WORDS: return "single"
        if r in _SLOT_DUO_WORDS:    return "duo"
    # default by presence of partner
    return "duo" if has_partner else "single"

def _weekday_from(s: str) -> int | None:
    return WEEKDAYS.get(s.strip().lower())

def _split_two_names(name_blob: str) -> tuple[str, str | None]:
    """
    Split "Mary and John" → ("Mary", "John").
    If only one name, returns (name, None).
    """
    s = name_blob.strip()
    m = re.match(r'(.+?)\s+(?:and|&)\s+(.+)$', s, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return s, None

# ──────────────────────────────────────────────────────────────────────────────
# Main parsers
# ──────────────────────────────────────────────────────────────────────────────
def parse_admin_command(text: str) -> dict | None:
    """
    Booking-related phrases.
    Returns a dict with keys 'intent' plus parameters or None if not matched.

    Supported:
      - book_single:  "Book Mary on 2025-09-01 08:00 [single|duo] [with John]"
      - book_recurring: "Book Mary every Tuesday 09h00 [single|duo]"
      - book_recurring_multi: "Book Mary and John every Tue 09h00 and Thu 10h00 [single|duo]"
    """
    s = text.strip()

    # 1) Single date booking (with optional type and partner)
    m = re.match(r'(?i)^\s*book\s+(.+?)\s+on\s+(\d{4}-\d{2}-\d{2})\s+([0-9:apmh]+|[0-2]?\dh[0-5]\d)(?:\s+(single|solo|1-1|duo|couple))?(?:\s+(?:with)\s+(.+))?\s*$', s)
    if m:
        name_blob, dstr, timestr, type_word, partner = m.groups()
        name, inferred_partner = _split_two_names(name_blob)
        hhmm = parse_time_word(timestr) or None
        if not hhmm: return None
        has_partner = bool(partner or inferred_partner)
        slot_type = _norm_slot_type(type_word, has_partner)
        return {
            "intent":"book_single",
            "name":name,
            "date":dstr,
            "time":hhmm,
            "slot_type":slot_type,
            "partner": (partner or inferred_partner)
        }

    # 2) Recurring (single day) — optional type, optional second name via "and X" in name_blob
    m = re.match(r'(?i)^\s*book\s+(.+?)\s+every\s+([a-z]+)\s+([0-9:apmh]+|[0-2]?\dh[0-5]\d)(?:\s+(single|solo|1-1|duo|couple))?\s*$', s)
    if m:
        name_blob, wday, timestr, type_word = m.groups()
        if _weekday_from(wday) is None: return None
        name, partner = _split_two_names(name_blob)
        hhmm = parse_time_word(timestr) or None
        if not hhmm: return None
        slot_type = _norm_slot_type(type_word, has_partner=bool(partner))
        return {
            "intent":"book_recurring",
            "name":name,
            "weekday":_weekday_from(wday),
            "time":hhmm,
            "slot_type":slot_type,
            "partner": partner,
            "until_cancelled": True
        }

    # 3) Recurring multi-day: "... every Tue 09h00 [single|duo] and Thu 10h00 [single|duo] ..."
    m = re.match(r'(?i)^\s*book\s+(.+?)\s+every\s+(.+?)\s*$', s)
    if m:
        name_blob, rest = m.groups()
        name, partner = _split_two_names(name_blob)

        # Split segments by " and "
        segments = re.split(r'(?i)\s+and\s+', rest.strip())
        slots = []
        for seg in segments:
            # pattern: "<weekday> <time> [type]"
            ms = re.match(r'(?i)^\s*([a-z]+)\s+([0-9:apmh]+|[0-2]?\dh[0-5]\d)(?:\s+(single|solo|1-1|duo|couple))?\s*$', seg.strip())
            if not ms:
                return None
            wday, timestr, type_word = ms.groups()
            wdi = _weekday_from(wday)
            if wdi is None:
                return None
            hhmm = parse_time_word(timestr) or None
            if not hhmm:
                return None
            slot_type = _norm_slot_type(type_word, has_partner=bool(partner))
            # For duo type, partner is required; if not supplied, keep None (admin can fix)
            slots.append({
                "weekday": wdi,
                "time": hhmm,
                "slot_type": slot_type,
                "partner": partner if slot_type == "duo" else None
            })

        if slots:
            return {
                "intent": "book_recurring_multi",
                "name": name,
                "slots": slots,               # list of {weekday,time,slot_type,partner?}
                "until_cancelled": True
            }

    # 4) Tomorrow helper
    m = re.match(r'(?i)^\s*book\s+(.+?)\s+tomorrow\s+([0-9:apmh]+|[0-2]?\dh[0-5]\d)(?:\s+(single|solo|1-1|duo|couple))?\s*$', s)
    if m:
        name_blob, timestr, type_word = m.groups()
        name, partner = _split_two_names(name_blob)
        hhmm = parse_time_word(timestr) or None
        if not hhmm:
            return None
        tomorrow = (datetime.utcnow() + timedelta(days=1)).date().isoformat()
        slot_type = _norm_slot_type(type_word, has_partner=bool(partner))
        return {"intent":"book_single","name":name,"date":tomorrow,"time":hhmm,"slot_type":slot_type,"partner":partner}

    return None

def parse_admin_client_command(text: str) -> dict | None:
    """
    Client & attendance updates:
      - "add client Alice with number 082..."
      - "change John date of birth to 21 May"
      - "update John - note text"
      - "cancel Jane next session"
      - "Peter is off sick."
      - "Sam is no show today."
    """
    s = text.strip()

    m = re.match(r'(?i)^\s*add\s+(?:new\s+)?client\s+(.+?)\s+(?:with\s+)?number\s+([+\d\s-]+)\s*$', s)
    if m:
        import re as _re
        name = m.group(1).strip()
        number = _re.sub(r'\s|-', '', m.group(2))
        return {"intent":"add_client","name":name,"number":number}

    m = re.match(r'(?i)^\s*change\s+(.+?)\s+date\s+of\s+birth\s+to\s+(\d{1,2})\s+([A-Za-z]+)\s*$', s)
    if m:
        name = m.group(1).strip()
        day = int(m.group(2)); mon_raw = m.group(3).lower()
        month = MONTHS.get(mon_raw)
        if not month:
            return None
        return {"intent":"update_dob","name":name,"day":day,"month":month}

    m = re.match(r'(?i)^\s*update\s+(.+?)\s*-\s*(.+)\s*$', s)
    if m:
        return {"intent":"update_medical","name":m.group(1).strip(),"note":m.group(2).strip()}

    m = re.match(r'(?i)^\s*cancel\s+(.+?)\s+next\s+session\s*$', s)
    if m:
        return {"intent":"cancel_next","name":m.group(1).strip()}

    m = re.match(r'(?i)^\s*(.+?)\s+is\s+off\s+sick\.?\s*$', s)
    if m:
        return {"intent":"off_sick_today","name":m.group(1).strip()}

    m = re.match(r'(?i)^\s*(.+?)\s+is\s+no\s+show\s+today\.?\s*$', s)
    if m:
        return {"intent":"no_show_today","name":m.group(1).strip()}

    return None
