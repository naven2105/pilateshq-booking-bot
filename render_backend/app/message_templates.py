# app/message_templates.py
from __future__ import annotations

from typing import List
from dataclasses import dataclass

@dataclass
class RowLike:
    start_time: str
    status: str
    booked_count: int
    capacity: int
    names: str

def fmt_rows_with_names(rows: List[RowLike]) -> str:
    if not rows:
        return "— none —"
    out = []
    for r in rows:
        full = (str(r.status).lower() == "full") or (int(r.booked_count) >= int(r.capacity))
        status = "🔒 full" if full else "✅ open"
        names = (r.names or "").strip()
        names_part = " (no bookings)" if not names else f" — {names}"
        out.append(f"• {str(r.start_time)[:5]}{names_part}  ({status})")
    return "\n".join(out)

def admin_today_block(rows: List[RowLike], label: str | None = None) -> str:
    header = label or ("🗓 Today’s sessions (upcoming)" if rows and rows[0].start_time else "🗓 Today’s sessions")
    return f"{header}\n{fmt_rows_with_names(rows)}"

def admin_next_hour_block(rows: List[RowLike]) -> str:
    if not rows:
        return "🕒 Next hour: no upcoming session."
    return "🕒 Next hour:\n" + fmt_rows_with_names(rows)

def admin_future_look_block(rows: List[RowLike]) -> str:
    if not rows:
        return "🔭 Tomorrow: no sessions scheduled."
    return "🔭 Tomorrow (preview):\n" + fmt_rows_with_names(rows)

# Client copy (removed 'CANCEL' instruction as requested)
def client_h1_text(hhmm: str) -> str:
    return f"⏰ Reminder: Your Pilates session starts at {hhmm} today. See you soon!"

def client_d1_text(hhmm: str) -> str:
    return f"📌 Reminder: Your Pilates session is tomorrow at {hhmm}. We’re looking forward to it!"
