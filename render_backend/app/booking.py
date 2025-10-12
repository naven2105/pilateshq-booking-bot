# app/booking.py
"""
booking.py
────────────────────────────────────────────
Handles client and admin bookings for PilatesHQ.
Now fully integrated with Google Sheets (no database).
────────────────────────────────────────────
Functions:
 - show_bookings() — Client view of upcoming sessions
 - admin_reserve() — Admin books a single session (posts to Sheets)
 - create_recurring_bookings() — Admin sets up a recurring booking
 - create_multi_recurring_bookings() — Admin creates multiple recurring slots
"""

from __future__ import annotations
import logging
import requests
from .utils import send_whatsapp_text, normalize_wa, safe_execute
from .config import NADINE_WA, WEB_APP_URL  # ✅ ensure WEB_APP_URL is defined in .config

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
    """Send a sample list of upcoming sessions to the client."""
    msg = (
        "📅 Your upcoming bookings:\n\n"
        "• Tue 24 Sep, 08:00 – Duo Session\n"
        "• Thu 26 Sep, 09:00 – Single Session\n\n"
        "If anything looks wrong, reply '0' and Nadine will assist."
    )
    safe_execute(send_whatsapp_text, wa_number, msg, label="client_show_bookings")


# ── Admin booking functions ───────────────────────────
def admin_reserve(
    name: str,
    date: str,
    time: str,
    slot_type: str,
    partner: str | None = None,
    wa_number: str | None = None,
):
    """
    Create a single booking entry and notify Nadine.
    Posts directly to Google Sheets via Apps Script Web App.
    """
    log.info(f"[booking.admin_reserve] Booking created for {name} ({slot_type}) on {date} {time}")

    # Build payload for Apps Script
    payload = {
        "action": "add_session",
        "session_date": date,
        "start_time": time,
        "client_name": name,
        "wa_number": wa_number or "",
        "session_type": slot_type.lower(),
        "status": "confirmed",
        "notes": partner or "",
    }

    try:
        res = requests.post(WEB_APP_URL, json=payload, timeout=10)
        if res.status_code == 200:
            log.info(f"[booking.admin_reserve] Added session to Sheets for {name}")
        else:
            log.warning(f"[booking.admin_reserve] Failed to post session ({res.status_code}): {res.text}")
    except Exception as e:
        log.exception(f"[booking.admin_reserve] Error posting to Sheets: {e}")

    if NADINE_WA:
        safe_execute(
            send_whatsapp_text,
            normalize_wa(NADINE_WA),
            f"✅ Booking created:\n👤 {name}{' & ' + partner if partner else ''}\n"
            f"📅 {date} {time}\n✨ {slot_type.title()}",
            label="admin_booking_notify",
        )


def create_recurring_bookings(
    name: str,
    weekday: int,
    time: str,
    slot_type: str,
    partner: str | None = None,
    wa_number: str | None = None,
):
    """
    Schedule a recurring booking each week.
    Logs and notifies Nadine (Sheets handled externally).
    """
    weekday_name = WEEKDAY_NAMES.get(weekday, f"Day {weekday}")
    log.info(f"[booking.recurring] {name} {slot_type} every {weekday_name} at {time}")

    if NADINE_WA:
        safe_execute(
            send_whatsapp_text,
            normalize_wa(NADINE_WA),
            f"✅ Recurring booking created:\n👤 {name}{' & ' + partner if partner else ''}\n"
            f"📅 Every {weekday_name}\n⏰ {time}\n✨ {slot_type.title()}",
            label="admin_recurring_notify",
        )


def create_multi_recurring_bookings(
    name: str,
    slots: list[dict],
    partner: str | None = None,
    wa_number: str | None = None,
):
    """
    Create multiple recurring bookings (e.g. Mon 08h00, Wed 09h00).
    Logs, posts each to Sheets, and notifies Nadine.
    """
    log.info(f"[booking.multi] Creating multi recurring bookings for {name}: {slots}")

    for s in slots:
        payload = {
            "action": "add_session",
            "session_date": s.get("date", ""),
            "start_time": s.get("time", ""),
            "client_name": name,
            "wa_number": wa_number or "",
            "session_type": s.get("slot_type", "session").lower(),
            "status": "confirmed",
            "notes": partner or "",
        }
        try:
            res = requests.post(WEB_APP_URL, json=payload, timeout=10)
            if res.status_code == 200:
                log.info(f"[booking.multi] Added session to Sheets: {payload}")
            else:
                log.warning(f"[booking.multi] Failed to post ({res.status_code}): {res.text}")
        except Exception as e:
            log.exception(f"[booking.multi] Error posting multi slot: {e}")

    if NADINE_WA:
        slot_lines = []
        for s in slots:
            weekday_name = WEEKDAY_NAMES.get(s.get("weekday"), s.get("weekday", "Day"))
            slot_lines.append(f"- {weekday_name} @ {s['time']} ({s['slot_type']})")
        details = "\n".join(slot_lines)
        safe_execute(
            send_whatsapp_text,
            normalize_wa(NADINE_WA),
            f"✅ Multi recurring bookings created:\n👤 {name}{' & ' + partner if partner else ''}\n{details}",
            label="admin_multi_notify",
        )
