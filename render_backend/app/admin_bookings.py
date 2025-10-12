#app/admin_bookings.py
"""
admin_bookings.py
────────────────────────────────────────────
Handles booking-related admin commands using Google Sheets integration.
Supports:
 - Single bookings
 - Recurring bookings
 - Multi-day recurring bookings
 - Cancel next booking
 - Mark sick / no-show today
"""

import logging
from datetime import date, timedelta
from .utils import (
    send_whatsapp_text,
    safe_execute,
    send_whatsapp_button,
    post_to_webhook,
)
from .admin_utils import _find_client_matches, _confirm_or_disambiguate
from .config import WEBHOOK_BASE

log = logging.getLogger(__name__)


# ── Helpers ─────────────────────────────────────────────
def normalize_time(t: str) -> str:
    """Convert admin style times like 08h00 → 08:00."""
    if not t:
        return t
    t = t.strip().lower()
    if "h" in t:
        try:
            hh, mm = t.split("h")
            return f"{int(hh):02d}:{int(mm):02d}"
        except Exception:
            pass
    return t


def _add_session_to_sheet(client_name, wa_number, session_date, start_time, slot_type, status="confirmed", notes=""):
    """
    Append a booking row to the Google Sheet via Apps Script endpoint.
    """
    payload = {
        "action": "add_session",
        "client_name": client_name,
        "wa_number": wa_number,
        "session_date": str(session_date),
        "start_time": start_time,
        "session_type": slot_type,
        "status": status,
        "notes": notes,
    }
    log.info(f"[Sheets] Adding session for {client_name} on {session_date} {start_time} ({slot_type})")
    post_to_webhook(f"{WEBHOOK_BASE}/sheets", payload)


def _notify_booking(client_name, wa_number, session_date, session_time, slot_type):
    """Send booking confirmation with Reject button."""
    msg = (
        f"📅 Nadine booked you for {session_date} at {session_time} ({slot_type}).\n\n"
        "If this is incorrect, tap ❌ Reject."
    )
    safe_execute(
        send_whatsapp_button,
        wa_number,
        msg,
        buttons=[{"id": f"reject_{session_date}_{session_time}", "title": "❌ Reject"}],
        label="client_booking_notify",
    )


# ── Main Dispatcher ─────────────────────────────────────
def handle_booking_command(parsed: dict, wa: str):
    """
    Routes parsed admin booking commands to Google Sheets integration.
    """
    intent = parsed["intent"]
    if "slot_type" not in parsed and "type" in parsed:
        parsed["slot_type"] = parsed["type"]

    log.info(f"[ADMIN BOOKING] parsed={parsed}")

    # ── Single Booking ───────────────────────────────
    if intent == "book_single":
        matches = _find_client_matches(parsed["name"])
        choice = _confirm_or_disambiguate(matches, "book session", wa)
        if not choice:
            return
        _, cname, wnum, _ = choice

        time_str = normalize_time(parsed["time"])
        _add_session_to_sheet(cname, wnum, parsed["date"], time_str, parsed["slot_type"])

        safe_execute(
            send_whatsapp_text,
            wa,
            f"✅ Session booked for {cname} on {parsed['date']} at {time_str}.",
            label="book_single_ok",
        )
        _notify_booking(cname, wnum, parsed["date"], time_str, parsed["slot_type"])
        return

    # ── Recurring Booking (weekly) ───────────────────
    if intent == "book_recurring":
        matches = _find_client_matches(parsed["name"])
        choice = _confirm_or_disambiguate(matches, "book recurring", wa)
        if not choice:
            return
        _, cname, wnum, _ = choice

        weekday = parsed["weekday"].lower()
        slot_time = normalize_time(parsed["time"])
        slot_type = parsed["slot_type"]

        created = 0
        today = date.today()
        for offset in range(0, 8 * 7):  # next 8 weeks
            d = today + timedelta(days=offset)
            if d.strftime("%A").lower() != weekday:
                continue
            _add_session_to_sheet(cname, wnum, d, slot_time, slot_type)
            created += 1

        safe_execute(
            send_whatsapp_text,
            wa,
            f"📅 Created {created} weekly bookings for {cname} ({slot_type}).",
            label="book_recurring",
        )
        return

    # ── Multi-day Recurring ──────────────────────────
    if intent == "book_recurring_multi":
        matches = _find_client_matches(parsed["name"])
        choice = _confirm_or_disambiguate(matches, "book recurring multi", wa)
        if not choice:
            return
        _, cname, wnum, _ = choice

        created = 0
        for slot in parsed["slots"]:
            if "slot_type" not in slot and "type" in slot:
                slot["slot_type"] = slot["type"]
            d, t, ty = slot["date"], normalize_time(slot["time"]), slot["slot_type"]
            _add_session_to_sheet(cname, wnum, d, t, ty)
            created += 1

        safe_execute(
            send_whatsapp_text,
            wa,
            f"📅 Created {created} recurring bookings for {cname} across multiple days.",
            label="book_multi",
        )
        return

    # ── Cancel Next ───────────────────────────────
    if intent == "cancel_next":
        matches = _find_client_matches(parsed["name"])
        choice = _confirm_or_disambiguate(matches, "cancel next booking", wa)
        if not choice:
            return
        _, cname, wnum, _ = choice

        payload = {"action": "cancel_next", "wa": wnum}
        post_to_webhook(f"{WEBHOOK_BASE}/sheets", payload)

        safe_execute(
            send_whatsapp_text,
            wa,
            f"✅ Next booking for {cname} cancelled and client notified.",
            label="cancel_next_ok",
        )
        return

    # ── Attendance Updates ───────────────────────────
    if intent in {"mark_sick", "mark_no_show"}:
        status = "sick" if "sick" in intent else "no_show"
        matches = _find_client_matches(parsed["name"])
        choice = _confirm_or_disambiguate(matches, f"mark {status}", wa)
        if not choice:
            return
        _, cname, wnum, _ = choice

        payload = {
            "action": "mark_today_status",
            "wa": wnum,
            "status": status,
        }
        post_to_webhook(f"{WEBHOOK_BASE}/sheets", payload)

        safe_execute(
            send_whatsapp_text,
            wa,
            f"✅ Marked {cname} as {status.replace('_','-')} today and client notified.",
            label=f"{status}_ok",
        )
        return
