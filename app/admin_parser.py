"""
admin_parser.py
────────────────
Parses raw admin WhatsApp text into structured dict commands for admin_clients.py
"""

import re


def parse_admin_command(body: str) -> dict | None:
    body = body.strip()

    # ── BOOK ──
    if body.lower().startswith("book "):
        m = re.match(
            r"book\s+(?P<name>[\w\s]+)\s+(?P<session_type>\w+)\s+(?P<day>\w+)\s+(?P<time>\d{2}h\d{2})(?:\s+dob=(?P<dob>[\d-]+))?(?:\s+health=(?P<health>.+))?",
            body,
            re.IGNORECASE,
        )
        if m:
            return {
                "intent": "book_client",
                "name": m.group("name").strip(),
                "session_type": m.group("session_type").lower(),
                "day": m.group("day"),
                "time": m.group("time"),
                "dob": m.group("dob"),
                "health": m.group("health"),
            }

    # ── CANCEL NEXT ──
    if body.lower().startswith("cancel "):
        name = body[7:].strip()
        return {"intent": "cancel_next", "name": name}

    # ── SICK TODAY ──
    if body.lower().startswith("sick "):
        name = body[5:].strip()
        return {"intent": "off_sick_today", "name": name}

    # ── NO-SHOW ──
    if body.lower().startswith("no-show "):
        name = body[8:].strip()
        return {"intent": "no_show_today", "name": name}

    # ── DEACTIVATE ──
    if body.lower().startswith("deactivate "):
        name = body[11:].strip()
        return {"intent": "deactivate", "name": name}

    if body.lower().startswith("confirm deactivate "):
        name = body[19:].strip()
        return {"intent": "confirm_deactivate", "name": name}

    # ── CANCEL DEACTIVATION ──
    if body.lower() == "cancel":
        return {"intent": "cancel"}

    return None
