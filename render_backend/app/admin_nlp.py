"""
admin_nlp.py
────────────
Lightweight natural-language parsing for admin commands.
Supports:
 - Bookings (book, recurring, cancel, status updates)
 - Client management (add, deactivate, update fields)
 - Invoices & balances
 - Session and invoice adjustments (Phase 9)
"""

import re


def parse_admin_command(text: str) -> dict | None:
    """Parse booking and operational admin commands."""
    if not text:
        return None
    s = text.strip().lower()

    # ── Book single ──
    m = re.match(
        r"book\s+(\w+)\s+(?:on\s+)?([0-9-]+|\w+)\s+(\d{1,2}[:h]\d{2}|\d{1,2}h)\s+(single|duo|trio)",
        s,
    )
    if m:
        return {
            "intent": "book_single",
            "name": m.group(1),
            "date": m.group(2),
            "time": m.group(3),
            "type": m.group(4),
        }

    # ── Book recurring ──
    m = re.match(
        r"book\s+(\w+)\s+every\s+(\w+)\s+(\d{1,2}[:h]\d{2}|\d{1,2}h)\s+(single|duo|trio)",
        s,
    )
    if m:
        return {
            "intent": "book_recurring",
            "name": m.group(1),
            "day": m.group(2),
            "time": m.group(3),
            "type": m.group(4),
        }

    # ── NEW: Change session type ──
    m = re.match(
        r"change\s+(.+?)\s+(\d{1,2}\s+\w+)\s+session\s+to\s+(single|duo|trio)",
        s,
    )
    if m:
        return {
            "intent": "update_session_type",
            "name": m.group(1).title(),
            "date": m.group(2),
            "new_type": m.group(3),
        }

    # ── NEW: Apply percentage discount ──
    m = re.match(r"take\s+(\d+)%\s+off\s+(.+?)\s+invoice", s)
    if m:
        return {
            "intent": "apply_discount_percent",
            "name": m.group(2).title(),
            "discount_value": int(m.group(1)),
        }

    # ── NEW: Apply fixed-amount discount ──
    m = re.match(r"take\s*r(\d+)\s+off\s+(.+?)\s+invoice", s)
    if m:
        return {
            "intent": "apply_discount_amount",
            "name": m.group(2).title(),
            "discount_value": float(m.group(1)),
        }

    return None


def parse_admin_client_command(text: str) -> dict | None:
    """Parse client and admin management commands."""
    if not text:
        return None
    s = text.strip()

    # ── Add client ──
    m = re.match(r"(?i)^add client\s+(.+)\s+with number\s+(\d+)$", s)
    if m:
        return {"intent": "add_client", "name": m.group(1).strip(), "number": m.group(2)}

    # ── Cancel next ──
    m = re.match(r"(?i)^cancel next\s+(\w+)$", s)
    if m:
        return {"intent": "cancel_next", "name": m.group(1)}

    # ── Sick today ──
    m = re.match(r"(?i)^(\w+)\s+(is )?(off )?sick$", s)
    if m:
        return {"intent": "off_sick_today", "name": m.group(1)}

    # ── No-show ──
    m = re.match(r"(?i)^(\w+)\s+(is )?(a )?no[- ]?show$", s)
    if m:
        return {"intent": "no_show_today", "name": m.group(1)}

    # ── Deactivate ──
    m = re.match(r"(?i)^deactivate\s+(.+)$", s)
    if m:
        return {"intent": "deactivate", "name": m.group(1).strip()}

    # ── Confirm deactivation ──
    m = re.match(r"(?i)^confirm deactivate\s+(.+)$", s)
    if m:
        return {"intent": "confirm_deactivate", "name": m.group(1).strip()}

    # ── Cancel (deactivation cancel) ──
    if s.strip().lower() in {"cancel", "abort"}:
        return {"intent": "cancel"}

    # ── Invoice ──
    m = re.match(r"(?i)^invoice\s+(.+?)(?:\s+([A-Za-z]+\s+\d{4}|this month|last month))?$", s)
    if m:
        return {
            "intent": "invoice",
            "name": m.group(1).strip(),
            "month": m.group(2),
        }

    # ── Balance ──
    m = re.match(r"(?i)^balance\s+(.+)$", s)
    if m:
        return {"intent": "balance", "name": m.group(1).strip()}

    return None
