# app/admin_nlp.py
import re
from datetime import datetime, timedelta
from typing import Optional, Tuple

WEEKDAYS = {
    "mon": 0, "monday": 0,
    "tue": 1, "tues": 1, "tuesday": 1,
    "wed": 2, "wednesday": 2,
    "thu": 3, "thurs": 3, "thursday": 3,
    "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5,
    "sun": 6, "sunday": 6,
}

def parse_time_word(t: str) -> Optional[str]:
    """Accept 7, 7am, 07:00, 07h00, 17h30 → return 'HH:MM' 24h."""
    t = t.lower().strip()
    # 07h00 / 7h00
    m = re.fullmatch(r'(\d{1,2})h(\d{2})', t)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
        return f"{hh:02d}:{mm:02d}"
    # 7am / 7pm / 7:30am
    m = re.fullmatch(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)', t)
    if m:
        hh = int(m.group(1)); mm = int(m.group(2) or 0)
        if m.group(3) == "pm" and hh != 12: hh += 12
        if m.group(3) == "am" and hh == 12: hh = 0
        return f"{hh:02d}:{mm:02d}"
    # 07:00 / 7:00
    m = re.fullmatch(r'(\d{1,2}):(\d{2})', t)
    if m:
        return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"
    # 7 → 07:00
    m = re.fullmatch(r'(\d{1,2})', t)
    if m:
        return f"{int(m.group(1)):02d}:00"
    return None

def parse_admin_command(text: str) -> Optional[dict]:
    """Return dict with intent or None if not matched."""
    s = text.strip().lower()

    # book <name> every <weekday> <time> [for <n> weeks]
    m = re.search(r'^book\s+(.+?)\s+every\s+([a-z]+)\s+([0-9:apmh]+|[0-2]?\dh[0-5]\d)(?:\s+for\s+(\d+)\s+weeks?)?$', s)
    if m:
        name, wday, timestr, weeks = m.group(1), m.group(2), m.group(3), m.group(4)
        if wday not in WEEKDAYS: return None
        hhmm = parse_time_word(timestr); 
        if not hhmm: return None
        return {"intent":"book_recurring","name":name.strip(),"weekday":WEEKDAYS[wday],"time":hhmm,"weeks":int(weeks or 4)}

    # book <name> on <yyyy-mm-dd> <time>
    m = re.search(r'^book\s+(.+?)\s+on\s+(\d{4}-\d{2}-\d{2})\s+([0-9:apmh]+|[0-2]?\dh[0-5]\d)$', s)
    if m:
        name, dstr, timestr = m.group(1), m.group(2), m.group(3)
        hhmm = parse_time_word(timestr); 
        if not hhmm: return None
        return {"intent":"book_single","name":name.strip(),"date":dstr,"time":hhmm}

    # book <name> tomorrow <time>
    m = re.search(r'^book\s+(.+?)\s+tomorrow\s+([0-9:apmh]+|[0-2]?\dh[0-5]\d)$', s)
    if m:
        name, timestr = m.group(1), m.group(2)
        hhmm = parse_time_word(timestr); 
        if not hhmm: return None
        tomorrow = (datetime.utcnow() + timedelta(days=1)).date().isoformat()
        return {"intent":"book_single","name":name.strip(),"date":tomorrow,"time":hhmm}

    return None
