# app/logic_models.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional, Literal, Dict, Tuple, Iterable

SlotType = Literal["single", "duo"]

@dataclass
class ClientLogic:
    id: str
    name: str
    wa_number: Optional[str] = None
    package_type: Optional[Literal["single","duo","trio"]] = None


@dataclass
class StandingSlot:
    client_id: str
    weekday: int
    time_hhmm: str
    slot_type: SlotType
    partner_id: Optional[str] = None
    until_cancelled: bool = True
    active: bool = True


@dataclass
class OneOffBooking:
    client_id: str
    date: date
    time_hhmm: str
    slot_type: SlotType
    partner_id: Optional[str] = None


# --- Helpers ---

def weekly_frequency(slots: Iterable[StandingSlot]) -> int:
    return sum(1 for s in slots if s.active and s.until_cancelled)


def weekly_slots_by_type(slots: Iterable[StandingSlot]) -> Dict[SlotType, int]:
    out: Dict[SlotType, int] = {"single": 0, "duo": 0}
    for s in slots:
        if s.active and s.until_cancelled:
            out[s.slot_type] += 1
    return out


def expected_weekly_from_package(package_type: Optional[str]) -> Optional[int]:
    return {"single": 1, "duo": 2, "trio": 3}.get(package_type or "", None)


def validate_package_alignment(client: ClientLogic, slots: Iterable[StandingSlot], tolerance: int = 1) -> Tuple[bool, str]:
    exp = expected_weekly_from_package(client.package_type)
    if exp is None:
        return True, "No package set; frequency derived from slots only."
    got = weekly_frequency(slots)
    if abs(got - exp) <= tolerance:
        return True, f"Aligned: expected ~{exp}/wk, reserved {got}/wk."
    return False, f"Mismatch: package ~{exp}/wk, reserved {got}/wk (soft warning)."


def _next_dates_for_weekday(start: date, weekday: int, count: int = 8) -> List[date]:
    days_ahead = (weekday - start.weekday()) % 7
    first = start + timedelta(days=days_ahead)
    return [first + timedelta(days=7*i) for i in range(count)]


def materialise_upcoming_from_standing(
    slots: Iterable[StandingSlot],
    today: Optional[date] = None,
    horizon_weeks: int = 4,
) -> List[Tuple[date, str, StandingSlot]]:
    base = today or date.today()
    out: List[Tuple[date, str, StandingSlot]] = []
    for s in slots:
        if not (s.active and s.until_cancelled):
            continue
        for d in _next_dates_for_weekday(base, s.weekday, count=horizon_weeks):
            out.append((d, s.time_hhmm, s))
    out.sort(key=lambda x: (x[0], x[1]))
    return out


def price_for_slot(slot_type: SlotType, price_table: Dict[SlotType, int]) -> int:
    return price_table[slot_type]


def weekly_price_estimate(slots: Iterable[StandingSlot], price_table: Dict[SlotType, int]) -> int:
    by_type = weekly_slots_by_type(slots)
    return sum(by_type[st] * price_for_slot(st, price_table) for st in by_type)
