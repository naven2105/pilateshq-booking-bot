from __future__ import annotations
from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Tuple, Dict
from collections import defaultdict
import calendar
import re

from sqlalchemy import text
from .db import db_session

# ──────────────────────────────────────────────────────────────────────────────
# Banking details & notes
# ──────────────────────────────────────────────────────────────────────────────

BANKING_LINES = [
    "Banking details",
    "Pilates HQ Pty Ltd",
    "Absa Bank",
    "Current Account",
    "Account No: 41171518 87",
]

NOTES_LINES = [
    "Payment is due on or before the due date.",
    "Use your name as a reference when making payment",
    "Kindly send me your POP via WhatsApp once you have made the payment.",
    "24 cancellation is required for your sessions to be made up",
    "Sessions will not be carried over into the following month",
    "Late cancellations of sessions will be charged.",
]

# ──────────────────────────────────────────────────────────────────────────────
# Pricing & classification
# ──────────────────────────────────────────────────────────────────────────────

def classify_type(capacity: int) -> str:
    if capacity <= 1:
        return "single"
    if capacity == 2:
        return "duo"
    if 3 <= capacity <= 6:
        return "group"
    return "group"

def rate_for_capacity(capacity: int) -> int:
    t = classify_type(capacity)
    return {"single": 300, "duo": 250, "group": 180}[t]

# ──────────────────────────────────────────────────────────────────────────────
# Month parsing
# ──────────────────────────────────────────────────────────────────────────────

_MONTHS = {
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

def _first_of_next_month(d: date) -> date:
    y, m = d.year, d.month
    return date(y + (1 if m == 12 else 0), 1 if m == 12 else m + 1, 1)

def parse_month_spec(spec: str) -> Tuple[date, date, str]:
    s = (spec or "").strip().lower()
    today = date.today()

    if s in ("this month", "thismonth", "tm"):
        start = date(today.year, today.month, 1)
        end = _first_of_next_month(start)
        return start, end, f"{calendar.month_name[start.month]} {start.year}"

    if s in ("last month", "lastmonth", "lm"):
        first_this = date(today.year, today.month, 1)
        last_prev = first_this - timedelta(days=1)
        start = date(last_prev.year, last_prev.month, 1)
        end = _first_of_next_month(start)
        return start, end, f"{calendar.month_name[start.month]} {start.year}"

    m = re.match(r"^\s*(\d{4})-(\d{1,2})\s*$", s)
    if m:
        y = int(m.group(1)); mnum = int(m.group(2))
        start = date(y, mnum, 1)
        end = _first_of_next_month(start)
        return start, end, f"{calendar.month_name[mnum]} {y}"

    parts = s.split()
    if len(parts) == 1 and parts[0] in _MONTHS:
        mnum = _MONTHS[parts[0]]
        y = today.year
        start = date(y, mnum, 1)
        end = _first_of_next_month(start)
        return start, end, f"{calendar.month_name[mnum]} {y}"

    if len(parts) >= 1 and parts[0] in _MONTHS:
        mnum = _MONTHS[parts[0]]
        y = today.year
        if len(parts) >= 2 and parts[1].isdigit():
            yraw = int(parts[1])
            y = 2000 + yraw if yraw < 100 else yraw
        start = date(y, mnum, 1)
        end = _first_of_next_month(start)
        return start, end, f"{calendar.month_name[mnum]} {y}"

    start = date(today.year, today.month, 1)
    end = _first_of_next_month(start)
    return start, end, f"{calendar.month_name[start.month]} {start.year}"

# ──────────────────────────────────────────────────────────────────────────────
# Data fetch + invoice builders
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class SessionRow:
    session_date: date
    start_time: str
    capacity: int
    status: str

def _fetch_client_rows(client_name: str, start_d: date, end_d: date) -> List[SessionRow]:
    sql = text("""
        SELECT s.session_date, s.start_time, s.capacity, b.status
        FROM bookings b
        JOIN sessions s ON s.id = b.session_id
        JOIN clients  c ON c.id = b.client_id
        WHERE c.name ILIKE :client_name
          AND b.status IN ('confirmed','cancelled')
          AND s.session_date >= :start_d
          AND s.session_date <  :end_d
        ORDER BY s.session_date, s.start_time
    """)
    with db_session() as s:
        rows = s.execute(sql, {
            "client_name": f"%{client_name}%",
            "start_d": start_d,
            "end_d": end_d
        }).all()
    out: List[SessionRow] = []
    for d, t, cap, st in rows:
        hhmm = t if isinstance(t, str) else f"{t.hour:02d}:{t.minute:02d}"
        out.append(SessionRow(d, hhmm, int(cap or 1), st))
    return out

def _totals(rows: List[SessionRow]) -> Dict[str, int]:
    confirmed = sum(1 for r in rows if r.status == "confirmed")
    cancelled = sum(1 for r in rows if r.status == "cancelled")
    billable_count = confirmed + cancelled
    billable_amount = sum(rate_for_capacity(r.capacity) for r in rows)
    return {
        "confirmed": confirmed,
        "cancelled": cancelled,
        "billable_count": billable_count,
        "billable_amount": billable_amount,
    }

# ──────────────────────────────────────────────────────────────────────────────
# WhatsApp short invoice
# ──────────────────────────────────────────────────────────────────────────────

def generate_invoice_whatsapp(client_name: str, month_spec: str, base_url: str) -> str:
    start_d, end_d, label = parse_month_spec(month_spec)
    rows = _fetch_client_rows(client_name, start_d, end_d)
    totals = _totals(rows)

    grouped: Dict[str, List[str]] = defaultdict(list)
    for r in rows:
        kind = classify_type(r.capacity)
        grouped[kind].append(str(r.session_date.day))

    lines = []
    lines.append(f"📑 PilatesHQ Invoice — {client_name}")
    lines.append(f"Period: {label}")
    lines.append("")

    if not rows:
        lines.append("No sessions this period.")
    else:
        lines.append("Sessions:")
        for kind, dates in grouped.items():
            rate = rate_for_capacity(1 if kind == "single" else (2 if kind == "duo" else 3))
            date_str = ", ".join(dates)
            lines.append(f"• {kind.title()}: {date_str} ({len(dates)}x R{rate})")
        lines.append("")
        lines.append(f"Total due: R{totals['billable_amount']}")

    lines.append("")
    lines.append("Banking details:")
    lines.extend(BANKING_LINES[1:])
    lines.append("")
    lines.append("Notes:")
    lines.append("• Use your name as reference")
    lines.append("• Send POP once paid")

    html_url = f"{base_url}/diag/invoice-html?client={client_name}&month={month_spec}"
    lines.append("")
    lines.append(f"🔗 Full invoice: {html_url}")
    return "\n".join(lines)

# ──────────────────────────────────────────────────────────────────────────────
# Payments & reconciliation
# ──────────────────────────────────────────────────────────────────────────────

def record_payment(client_name: str, amount: float, pay_date: date, notes: str = "") -> int:
    sql = text("INSERT INTO payments (client_id, amount, date_received, notes) "
               "SELECT c.id, :amount, :date_received, :notes "
               "FROM clients c WHERE c.name ILIKE :client_name RETURNING id")
    with db_session() as s:
        row = s.execute(sql, {
            "client_name": f"%{client_name}%",
            "amount": amount,
            "date_received": pay_date,
            "notes": notes,
        }).first()
        s.commit()
    return row[0] if row else -1

def fetch_payments(client_name: str, start_d: date, end_d: date) -> List[Tuple[date, float, str]]:
    sql = text("""
        SELECT p.date_received, p.amount, p.notes
        FROM payments p
        JOIN clients c ON c.id = p.client_id
        WHERE c.name ILIKE :client_name
          AND p.date_received >= :start_d
          AND p.date_received < :end_d
        ORDER BY p.date_received
    """)
    with db_session() as s:
        rows = s.execute(sql, {
            "client_name": f"%{client_name}%",
            "start_d": start_d,
            "end_d": end_d
        }).all()
    return [(r[0], float(r[1]), r[2]) for r in rows]

def generate_payments_report(month_spec: str) -> str:
    start_d, end_d, label = parse_month_spec(month_spec)

    sql = text("SELECT id, name FROM clients ORDER BY name")
    with db_session() as s:
        clients = s.execute(sql).all()

    lines = [f"📊 Payments report — {label}", ""]
    for cid, cname in clients:
        rows = _fetch_client_rows(cname, start_d, end_d)
        totals = _totals(rows)
        billed = totals["billable_amount"]

        pays = fetch_payments(cname, start_d, end_d)
        paid = sum(p[1] for p in pays)
        balance = billed - paid

        lines.append(f"{cname}: billed R{billed}, paid R{paid}, balance R{balance}")
    return "\n".join(lines)
