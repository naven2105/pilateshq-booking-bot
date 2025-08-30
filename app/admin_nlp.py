# app/admin_nlp.py
"""
Lightweight natural-language parsing for admin shortcuts.
Converts phrases like:
  - "Book Mary on 2025-09-01 08:00"
  - "Book Peter every Monday 8am for 4 weeks"
  - "John is no show today"
into structured intents for admin.py to execute.
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

def parse_admin_command(text: str) -> dict | None:
    """
    Booking-related phrases.
    Returns a dict with keys 'intent' plus parameters or None if not matched.
    """
    s = text.strip().lower()
    m = re.search(r'^book\s+(.+?)\s+every\s+([a-z]+)\s+([0-9:apmh]+|[0-2]?\dh[0-5]\d)(?:\s+for\s+(\d+)\s+weeks?)?$', s)
    if m:
        name, wday, timestr, weeks = m.group(1), m.group(2), m.group(3), m.group(4)
        if wday not in WEEKDAYS:
            return None
        hhmm = parse_time_word(timestr) or None
        if not hhmm:
            return None
        return {"intent":"book_recurring","name":name.strip(),"weekday":WEEKDAYS[wday],"time":hhmm,"weeks":int(weeks or 4)}

    m = re.search(r'^book\s+(.+?)\s+on\s+(\d{4}-\d{2}-\d{2})\s+([0-9:apmh]+|[0-2]?\dh[0-5]\d)$', s)
    if m:
        name, dstr, timestr = m.group(1), m.group(2), m.group(3)
        hhmm = parse_time_word(timestr) or None
        if not hhmm:
            return None
        return {"intent":"book_single","name":name.strip(),"date":dstr,"time":hhmm}

    m = re.search(r'^book\s+(.+?)\s+tomorrow\s+([0-9:apmh]+|[0-2]?\dh[0-5]\d)$', s)
    if m:
        name, timestr = m.group(1), m.group(2)
        hhmm = parse_time_word(timestr) or None
        if not hhmm:
            return None
        tomorrow = (datetime.utcnow() + timedelta(days=1)).date().isoformat()
        return {"intent":"book_single","name":name.strip(),"date":tomorrow,"time":hhmm}

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
