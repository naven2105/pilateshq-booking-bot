#app/invoices.py

from __future__ import annotations
from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Tuple, Dict
from collections import defaultdict
import calendar, re

from sqlalchemy import text
from .db import db_session
from weasyprint import HTML

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
# Data fetch + helpers
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

def _fetch_client_id(client_name: str) -> int | None:
    sql = text("SELECT id FROM clients WHERE name ILIKE :cname LIMIT 1")
    with db_session() as s:
        cid = s.execute(sql, {"cname": f"%{client_name}%"}).scalar()
    return cid

def _fetch_payments(client_id: int, start_d: date, end_d: date) -> float:
    sql = text("""
        SELECT COALESCE(SUM(amount),0)
        FROM payments
        WHERE client_id = :cid
          AND date_received >= :start_d
          AND date_received < :end_d
    """)
    with db_session() as s:
        amt = s.execute(sql, {"cid": client_id, "start_d": start_d, "end_d": end_d}).scalar()
    return float(amt or 0)

def _fetch_client_payments(client_name: str, start_d: date, end_d: date) -> float:
    cid = _fetch_client_id(client_name)
    if not cid:
        return 0.0
    return _fetch_payments(cid, start_d, end_d)

# ──────────────────────────────────────────────────────────────────────────────
# Invoice generators (WhatsApp / HTML / PDF)
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
    pdf_url = f"{base_url}/diag/invoice-pdf?client={client_name}&month={month_spec}"
    lines.append("")
    lines.append(f"🔗 Full invoice (PDF): {pdf_url}")
    lines.append(f"🔗 Preview (HTML): {html_url}")
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
        rows_html = "<tr><td colspan='5' class='muted'>No sessions found for this period.</td></tr>"

    bank_html = "<br>".join(BANKING_LINES)
    notes_html = "".join([f"<li>{x}</li>" for x in NOTES_LINES])

    # Payments
    paid = _fetch_client_payments(client_name, start_d, end_d)
    balance = totals["billable_amount"] - paid

    paid_html = (
        f"<p><b>Amount billed:</b> R{totals['billable_amount']}<br>"
        f"<b>Payments received:</b> R{paid}<br>"
        f"<b>Balance due:</b> R{balance}</p>"
    )
    if balance <= 0:
        paid_html += "<p style='color:green; font-weight:bold;'>✅ Paid in full</p>"

    html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>PilatesHQ Invoice — {client_name} — {label}</title>
<style>
  body {{ font-family: system-ui, Arial, sans-serif; margin: 24px; color: #111; }}
  h1 {{ margin: 0 0 6px 0; font-size: 20px; }}
  h2 {{ margin: 0 0 18px 0; font-size: 14px; font-weight: normal; color: #555; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
  th, td {{ border: 1px solid #ddd; padding: 8px; font-size: 13px; }}
  th {{ background: #f7f7f7; text-align: left; }}
  .right {{ text-align: right; }}
  .muted {{ color: #666; }}
</style>
</head>
<body>
  <h1>PilatesHQ — Invoice</h1>
  <h2>Client: {client_name} • Period: {label}</h2>
  <table>
    <thead>
      <tr><th>Date</th><th>Time</th><th>Type</th><th class="right">Rate</th><th>Status</th></tr>
    </thead>
    <tbody>{rows_html}</tbody>
  </table>
  <p><b>Confirmed:</b> {totals['confirmed']} • <b>Cancelled:</b> {totals['cancelled']}<br>
  <b>Total sessions billed:</b> {totals['billable_count']}</p>
  {paid_html}
  <h3>Banking details</h3>
  <div>{bank_html}</div>
  <h3>Notes</h3>
  <ul>{notes_html}</ul>
</body>
</html>"""
    return html


def generate_invoice_pdf(client_name: str, month_spec: str) -> bytes:
    html_str = generate_invoice_html(client_name, month_spec)
    pdf_bytes = HTML(string=html_str).write_pdf()
    return pdf_bytes
