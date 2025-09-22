# app/booking.py
from __future__ import annotations
import logging
from .utils import send_whatsapp_text, normalize_wa
from .config import NADINE_WA

log = logging.getLogger(__name__)

# ── Weekday mapping ──────────────────────────────────
WEEKDAY_NAMES = {
    0: "Monday",
    1: "Tuesday",
    2: "Wednesday",
    3: "Thursday",
    4: "Friday",
    5: "Saturday",
    6: "Sunday",
}

# ── Client: show bookings ─────────────────────────────
def show_bookings(wa_number: str):
    """
    Show upcoming bookings for a client.
    Replace with real DB queries later.
    """
    msg = (
        "📅 Your upcoming bookings:\n\n"
        "• Tue 24 Sep, 08:00 – Reformer Duo\n"
        "• Thu 26 Sep, 09:00 – Reformer Single\n\n"
        "If anything looks wrong, reply '0' and Nadine will assist."
    )
    send_whatsapp_text(wa_number, msg)


# ── Admin: booking functions ──────────────────────────
def admin_reserve(name: str, date: str, time: str, slot_type: str, partner: str | None = None):
    """
    Single admin booking (via NLP).
    Replace with DB insert logic later.
    """
    msg = f"[ADMIN] Reserving {slot_type} for {name} on {date} {time}"
    if partner:
        msg += f" with {partner}"
    log.info(msg)

    if NADINE_WA:
        send_whatsapp_text(
            normalize_wa(NADINE_WA),
            f"✅ Booking created:\n👤 {name}{' & ' + partner if partner else ''}\n"
            f"📅 {date} {time}\n✨ {slot_type.title()}"
        )


def create_recurring_bookings(name: str, weekday: int, time: str, slot_type: str, partner: str | None = None):
    """
    Recurring admin bookings (single weekday).
    weekday = 0 (Mon) … 6 (Sun)
    """
    weekday_name = WEEKDAY_NAMES.get(weekday, f"Day {weekday}")
    msg = f"[ADMIN] Recurring {slot_type} booking for {name} every {weekday_name} at {time}"
    if partner:
        msg += f" with {partner}"
    log.info(msg)

    if NADINE_WA:
        send_whatsapp_text(
            normalize_wa(NADINE_WA),
            f"✅ Recurring booking created:\n👤 {name}{' & ' + partner if partner else ''}\n"
            f"📅 Every {weekday_name}\n⏰ {time}\n✨ {slot_type.title()}"
        )


def create_multi_recurring_bookings(name: str, slots: list[dict], partner: str | None = None):
    """
    Multi-day recurring bookings.
    slots = list of {weekday, time, slot_type, partner?}
    """
    msg = f"[ADMIN] Multi recurring bookings for {name}: {slots}"
    log.info(msg)

    if NADINE_WA:
        slot_lines = []
        for s in slots:
            weekday_name = WEEKDAY_NAMES.get(s["weekday"], f"Day {s['weekday']}")
            slot_lines.append(
                f"- {weekday_name} @ {s['time']} ({s['slot_type']})"
            )
        details = "\n".join(slot_lines)
        send_whatsapp_text(
            normalize_wa(NADINE_WA),
            f"✅ Multi recurring bookings created:\n👤 {name}{' & ' + partner if partner else ''}\n{details}"
        )
