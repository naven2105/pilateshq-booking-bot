# app/message_templates.py
from __future__ import annotations

"""
Utility formatting for admin/client WhatsApp messages.

- Accepts flexible row inputs (dataclass, dict, or object with attributes)
- Robust time formatting from str | datetime.time | datetime
- Sensible badges for full/cancelled/open based on status and counts
"""

from dataclasses import dataclass
from datetime import datetime, time
from typing import Any, Iterable, List, Optional, Protocol, Union


# ─────────────────────────────────────────────────────────────
# Row shape & adapters
# ─────────────────────────────────────────────────────────────

class SupportsRow(Protocol):
    start_time: Any
    status: Any
    booked_count: Any
    capacity: Any
    names: Any


@dataclass
class RowLike:
    start_time: Any
    status: Any
    booked_count: Any
    capacity: Any
    names: Any


# ─────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────

def _as_int(val: Any, default: int = 0) -> int:
    try:
        return int(val)
    except Exception:
        return default


def _norm_status(val: Any) -> str:
    s = (str(val) if val is not None else "").strip().lower()
    return s


def _fmt_hhmm(t: Any) -> str:
    """
    Accepts:
      - '09:00', '9:00', '09h00', '9h'
      - datetime.time
      - datetime
    Returns 'HH:MM'. Falls back to raw str if parsing fails.
    """
    if isinstance(t, time):
        return t.strftime("%H:%M")
    if isinstance(t, datetime):
        return t.strftime("%H:%M")

    s = (str(t) if t is not None else "").strip()
    if not s:
        return "—:—"

    # Normalise "09h00" → "09:00", "9h" → "09:00"
    s2 = s.lower().replace("h", ":")
    if s2.endswith(":"):
        s2 += "00"

    # Ensure zero-padded hour
    try:
        if ":" in s2:
            hh, mm = s2.split(":", 1)
            hh = hh.zfill(2)
            mm = mm.zfill(2)[:2]
            # Validate
            hhi = int(hh); mmi = int(mm)
            if 0 <= hhi < 24 and 0 <= mmi < 60:
                return f"{hh}:{mm}"
    except Exception:
        pass

    # Last resort: best-effort slice like the old code
    return s[:5] if len(s) >= 5 else s


def _status_badge(status: str, booked: int, capacity: int) -> str:
    """
    Priority:
      cancelled -> '🚫 cancelled'
      full (or booked>=capacity) -> '🔒 full'
      else -> '✅ open'
    """
    if "cancel" in status:
        return "🚫 cancelled"
    if "full" in status or (capacity > 0 and booked >= capacity):
        return "🔒 full"
    return "✅ open"


def _clean_names(names: Any) -> str:
    """
    Accept comma/pipe-separated name strings, collapse whitespace,
    and trim length to keep WhatsApp lines tidy.
    """
    s = (str(names) if names is not None else "").strip()
    if not s:
        return ""
    # Normalise separators
    s = s.replace("|", ",")
    parts = [p.strip() for p in s.split(",") if p.strip()]
    out = ", ".join(parts)
    return out[:200]  # safety cap for message width


# ─────────────────────────────────────────────────────────────
# Public formatting functions
# ─────────────────────────────────────────────────────────────

def fmt_rows_with_names(rows: List[SupportsRow]) -> str:
    """
    Render bullet lines like:
      • 09:00 — Mary, Tom  (✅ open)
      • 17:30 —  (no bookings)  (🔒 full)
    """
    if not rows:
        return "— none —"

    out: List[str] = []
    for r in rows:
        st = _fmt_hhmm(getattr(r, "start_time", None) if hasattr(r, "start_time") else r.get("start_time"))  # type: ignore
        status_raw = getattr(r, "status", None) if hasattr(r, "status") else r.get("status")  # type: ignore
        booked_raw = getattr(r, "booked_count", None) if hasattr(r, "booked_count") else r.get("booked_count")  # type: ignore
        cap_raw = getattr(r, "capacity", None) if hasattr(r, "capacity") else r.get("capacity")  # type: ignore
        names_raw = getattr(r, "names", None) if hasattr(r, "names") else r.get("names")  # type: ignore

        status = _norm_status(status_raw)
        booked = _as_int(booked_raw, 0)
        capacity = _as_int(cap_raw, 0)
        badge = _status_badge(status, booked, capacity)

        names = _clean_names(names_raw)
        names_part = " (no bookings)" if not names else f" — {names}"
        out.append(f"• {st}{names_part}  ({badge})")

    return "\n".join(out)


def admin_today_block(rows: List[SupportsRow], label: Optional[str] = None) -> str:
    """
    Header + today’s rows.
    """
    header = label or "🗓 Today’s sessions"
    return f"{header}\n{fmt_rows_with_names(rows)}"


def admin_next_hour_block(rows: List[SupportsRow]) -> str:
    """
    Header + next-hour rows (or a friendly empty line).
    """
    if not rows:
        return "🕒 Next hour: no upcoming session."
    return "🕒 Next hour:\n" + fmt_rows_with_names(rows)


def admin_future_look_block(rows: List[SupportsRow]) -> str:
    """
    Header + tomorrow preview rows (or a friendly empty line).
    """
    if not rows:
        return "🔭 Tomorrow: no sessions scheduled."
    return "🔭 Tomorrow (preview):\n" + fmt_rows_with_names(rows)


# Client copy (uses plain text for non-template fallbacks)
def client_h1_text(hhmm: Union[str, time, datetime]) -> str:
    return f"⏰ Reminder: Your Pilates session starts at {_fmt_hhmm(hhmm)} today. See you soon!"


def client_d1_text(hhmm: Union[str, time, datetime]) -> str:
    return f"📌 Reminder: Your Pilates session is tomorrow at {_fmt_hhmm(hhmm)}. We’re looking forward to it!"
