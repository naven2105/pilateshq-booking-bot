# app/models.py
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import List, Optional, Literal, Dict, Tuple, Iterable
import calendar

SlotType = Literal["single", "duo"]

@dataclass
class Client:
    id: str
    name: str
    wa_number: Optional[str] = None
    package_type: Optional[Literal["single","duo","trio"]] = None  # optional for billing/reporting

@dataclass
class StandingSlot:
    """
    A recurring reservation on a specific weekday/time.
    Example: weekday=1 (Tue), time_hhmm="09:00", slot_type="duo", partner_id="cli_002"
    """
    client_id: str
    weekday: int                        # 0=Mon .. 6=Sun
    time_hhmm: str                      # "HH:MM" 24h
    slot_type: SlotType                 # single | duo
    partner_id: Optional[str] = None    # required for duo; None for single
    until_cancelled: bool = True        # standing unless explicitly ended
    active: bool = True

@dataclass
class OneOffBooking:
    client_id: str
    date: date
    time_hhmm: str
    slot_type: SlotType
    partner_id: Optional[str] = None

# ──────────────────────────────────────────────────────────────────────────────
# Frequency = derived from slots (do not store)
# ──────────────────────────────────────────────────────────────────────────────
def weekly_frequency(slots: Iterable[StandingSlot]) -> int:
    """Count distinct active recurring slots per week (derived)."""
    return sum(1 for s in slots if s.active and s.until_cancelled)

def weekly_slots_by_type(slots: Iterable[StandingSlot]) -> Dict[SlotType, int]:
    out: Dict[SlotType, int] = {"single": 0, "duo": 0}
    for s in slots:
        if s.active and s.until_cancelled:
            out[s.slot_type] += 1
    return out

# ──────────────────────────────────────────────────────────────────────────────
# Guardrails vs package (soft checks, never hard-block scheduling)
# ──────────────────────────────────────────────────────────────────────────────
def expected_weekly_from_package(package_type: Optional[str]) -> Optional[int]:
    return {"single": 1, "duo": 2, "trio": 3}.get(package_type or "", None)

def validate_package_alignment(
    client: Client, slots: Iterable[StandingSlot], tolerance: int = 1
) -> Tuple[bool, str]:
    """
    Returns (ok, message). Soft validation:
      - If client has a package_type, compare derived weekly frequency to expected.
      - Allow +/- tolerance to avoid blocking operational reality.
    """
    exp = expected_weekly_from_package(client.package_type)
    if exp is None:
        return True, "No package set; frequency derived from slots only."
    got = weekly_frequency(slots)
    if abs(got - exp) <= tolerance:
        return True, f"Aligned: expected ~{exp}/wk, reserved {got}/wk."
    return False, f"Mismatch: package ~{exp}/wk, reserved {got}/wk (soft warning)."

# ──────────────────────────────────────────────────────────────────────────────
# Utilities to materialise upcoming sessions from standing slots
# ──────────────────────────────────────────────────────────────────────────────
def _next_dates_for_weekday(start: date, weekday: int, count: int = 8) -> List[date]:
    """Generate next N dates on a given weekday starting today."""
    days_ahead = (weekday - start.weekday()) % 7
    first = start + timedelta(days=days_ahead)
    return [first + timedelta(days=7*i) for i in range(count)]

def materialise_upcoming_from_standing(
    slots: Iterable[StandingSlot],
    today: Optional[date] = None,
    horizon_weeks: int = 4,
) -> List[Tuple[date, str, StandingSlot]]:
    """
    Produce upcoming (date, time_hhmm, slot) tuples for calendar previews, reminders, etc.
    """
    base = today or date.today()
    out: List[Tuple[date, str, StandingSlot]] = []
    for s in slots:
        if not (s.active and s.until_cancelled):
            continue
        for d in _next_dates_for_weekday(base, s.weekday, count=horizon_weeks):
            out.append((d, s.time_hhmm, s))
    # Sort by date/time
    out.sort(key=lambda x: (x[0], x[1]))
    return out

# ──────────────────────────────────────────────────────────────────────────────
# Pricing helpers (slot-level, supports mixed commitments)
# ──────────────────────────────────────────────────────────────────────────────
def price_for_slot(slot_type: SlotType, price_table: Dict[SlotType, int]) -> int:
    """
    Returns integer price (e.g., R) for a slot based on slot_type.
    Example price_table = {"single": 300, "duo": 250}
    """
    return price_table[slot_type]

def weekly_price_estimate(slots: Iterable[StandingSlot], price_table: Dict[SlotType, int]) -> int:
    """
    Derived, rough weekly revenue estimate for a client's standing reservations.
    """
    by_type = weekly_slots_by_type(slots)
    return sum(by_type[st] * price_for_slot(st, price_table) for st in by_type)
