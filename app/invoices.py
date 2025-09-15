# app/invoices.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import List, Tuple, Dict
import calendar
import re

# Banking details & notes (rendered in both text and HTML)
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


from sqlalchemy import text

from .db import db_session

# ──────────────────────────────────────────────────────────────────────────────
# Pricing & classification
# ──────────────────────────────────────────────────────────────────────────────

def classify_type(capacity: int) -> str:
    """
    Map session capacity → commercial type.
    - 1 → single
    - 2 → duo
    - 3..6 → group
    (Guard: anything <=0 defaults to single; anything >6 treated as group.)
    """
    if capacity <= 1:
        return "single"
    if capacity == 2:
        return "duo"
    if 3 <= capacity <= 6:
        return "group"
    return "group"

def rate_for_capacity(capacity: int) -> int:
    """
    Rates (ZAR):
      single=300, duo=250, group=180
    """
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
    if m == 12:
        return date(y + 1, 1, 1)
    return date(y, m + 1, 1)

def parse_month_spec(spec: str) -> Tuple[date, date, str]:
    """
    Accepts:
      - "this month", "last month"
      - "sept", "september 2025", "oct 24"
      - "2025-09" (YYYY-MM)
    Returns: (start_date, end_date_exclusive, pretty_label)
    """
    s = (spec or "").strip().lower()
    today = date.today()

    if s in ("this month", "thismonth", "tm"):
        start = date(today.year, today.month, 1)
        end = _first_of_next_month(start)
        label = f"{calendar.month_name[start.month]} {start.year}"
        return start, end, label

    if s in ("last month", "lastmonth", "lm"):
        # go to first of this month, subtract one day → last month
        first_this = date(today.year, today.month, 1)
        last_prev = first_this - timedelta(days=1)
        start = date(last_prev.year, last_prev.month, 1)
        end = _first_of_next_month(start)
        label = f"{calendar.month_name[start.month]} {start.year}"
        return start, end, label

    # YYYY-MM
    m = re.match(r"^\s*(\d{4})-(\d{1,2})\s*$", s)
    if m:
        y = int(m.group(1)); mnum = int(m.group(2))
        start = date(y, mnum, 1)
        end = _first_of_next_month(start)
        return start, end, f"{calendar.month_name[mnum]} {y}"

    # "sept", "september 2025", "oct 24"
    parts = s.split()
    if len(parts) == 1 and parts[0] in _MONTHS:
        mnum = _MONTHS[parts[0]]
        y = today.year
        start = date(y, mnum, 1)
        end = _first_of_next_month(start)
        return start, end, f"{calendar.month_name[mnum]} {y}"

    if len(parts) >= 1 and parts[0] in _MONTHS:
        mnum = _MONTHS[parts[0]]
        # year may be 2-digit or 4-digit
        if len(parts) >= 2 and parts[1].isdigit():
            yraw = int(parts[1])
            y = 2000 + yraw if yraw < 100 else yraw
        else:
            y = today.year
        start = date(y, mnum, 1)
        end = _first_of_next_month(start)
        return start, end, f"{calendar.month_name[mnum]} {y}"

    # Fallback: treat as "this month"
    start = date(today.year, today.month, 1)
    end = _first_of_next_month(start)
    label = f"{calendar.month_name[start.month]} {start.year}"
    return start, end, label

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

def generate_invoice_text(client_name: str, month_spec: str) -> str:
    start_d, end_d, label = parse_month_spec(month_spec)
    rows = _fetch_client_rows(client_name, start_d, end_d)
    totals = _totals(rows)

    def banking_block() -> List[str]:
        out = [""]
        out.append("—")
        out.extend(BANKING_LINES)
        out.append("")
        out.append("Notes:")
        out.extend([f"• {x}" for x in NOTES_LINES])
        return out

    if not rows:
        lines = [
            f"PilatesHQ Invoice — {client_name}",
            f"Period: {label}",
            "",
            "No sessions found for this period.",
            "If you missed classes, reply *BOOK* to schedule — we’re missing you! 💪",
        ]
        lines.extend(banking_block())
        return "\n".join(lines)

    lines = []
    lines.append(f"PilatesHQ Invoice — {client_name}")
    lines.append(f"Period: {label}")
    lines.append("")
    lines.append("Sessions:")
    for r in rows:
        kind = classify_type(r.capacity)
        rate = rate_for_capacity(r.capacity)
        lines.append(f"• {r.session_date} {r.start_time} — {kind.title()} (R{rate}) — {r.status}")
    lines.append("")
    lines.append(f"Confirmed: {totals['confirmed']}  |  Cancelled (still billable, credit carried): {totals['cancelled']}")
    lines.append(f"Total sessions billed: {totals['billable_count']}")
    lines.append(f"Amount due: R{totals['billable_amount']}")
    lines.append("")
    lines.append("Note: Cancelled bookings remain billable. Credits carry over to the next cycle.")
    lines.extend(banking_block())
    return "\n".join(lines)

def generate_invoice_html(client_name: str, month_spec: str) -> str:
    start_d, end_d, label = parse_month_spec(month_spec)
    rows = _fetch_client_rows(client_name, start_d, end_d)
    totals = _totals(rows)

    rows_html = ""
    if rows:
        for r in rows:
            kind = classify_type(r.capacity)
            rate = rate_for_capacity(r.capacity)
            rows_html += (
                f"<tr>"
                f"<td>{r.session_date}</td>"
                f"<td>{r.start_time}</td>"
                f"<td>{kind.title()}</td>"
                f"<td class='right'>R{rate}</td>"
                f"<td>{r.status}</td>"
                f"</tr>"
            )
    else:
        rows_html = (
            "<tr><td colspan='5' class='muted'>No sessions found for this period."
            " If you missed classes, book your next one — we’re missing you! 💪</td></tr>"
        )

    bank_html = "<br>".join(BANKING_LINES)
    notes_html = "".join([f"<li>{x}</li>" for x in NOTES_LINES])

    html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>PilatesHQ Invoice — {client_name} — {label}</title>
<style>
  body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 24px; color: #111; }}
  h1 {{ margin: 0 0 6px 0; font-size: 20px; }}
  h2 {{ margin: 0 0 18px 0; font-size: 14px; font-weight: normal; color: #555; }}
  h3 {{ margin: 18px 0 6px 0; font-size: 14px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
  th, td {{ border: 1px solid #ddd; padding: 8px; font-size: 13px; }}
  th {{ background: #f7f7f7; text-align: left; }}
  .right {{ text-align: right; }}
  .muted {{ color: #666; }}
  .summary {{ margin-top: 16px; font-size: 13px; }}
  .totals {{ margin-top: 6px; font-weight: 600; }}
  .note {{ margin-top: 12px; font-size: 12px; color: #555; }}
  @media print {{
    body {{ margin: 0; }}
    .no-print {{ display: none; }}
  }}
</style>
</head>
<body>
  <div class="no-print" style="text-align:right;">
    <button onclick="window.print()">Print / Save as PDF</button>
  </div>
  <h1>PilatesHQ — Invoice</h1>
  <h2>Client: {client_name} &nbsp;•&nbsp; Period: {label}</h2>

  <table>
    <thead>
      <tr>
        <th>Date</th><th>Time</th><th>Type</th><th class="right">Rate</th><th>Status</th>
      </tr>
    </thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>

  <div class="summary">
    Confirmed: {totals['confirmed']} &nbsp;|&nbsp; Cancelled (billable): {totals['cancelled']}<br>
    Total sessions billed: {totals['billable_count']}<br>
    <span class="totals">Amount due: R{totals['billable_amount']}</span>
  </div>

  <h3>Banking details</h3>
  <div>{bank_html}</div>

  <h3>Notes</h3>
  <ul>
    {notes_html}
  </ul>

  <div class="note">
    Note: Cancelled bookings remain billable; credits carry to the next cycle.
  </div>
</body>
</html>"""
    return html
