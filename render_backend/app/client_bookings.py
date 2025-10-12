#app/client_bookings.py
"""
client_bookings.py
──────────────────
Handles client booking queries (view, cancel next, cancel specific)
using Google Sheets via the Apps Script API.
"""

import logging
import requests
from datetime import datetime
from .utils import send_whatsapp_text, safe_execute, normalize_wa

log = logging.getLogger(__name__)

# Your deployed Google Apps Script URL
APPS_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbzXQgwxZZDisjHRs78yQeG7xsDNynSLLKcAV57fn1mflZa1dtCKdNvK-0YpkqNtyJiBqQ/exec"


# ───────────────────────────────────────────────
# 🔹 Show upcoming sessions
# ───────────────────────────────────────────────
def show_bookings(wa_number: str):
    """Fetch and show upcoming sessions for a client via Google Sheets."""
    try:
        payload = {"action": "get_upcoming_sessions", "wa": wa_number}
        res = requests.post(APPS_SCRIPT_URL, json=payload, timeout=15)
        data = res.json() if res.status_code == 200 else {}

        sessions = data.get("sessions", [])
        if not sessions:
            safe_execute(
                send_whatsapp_text,
                wa_number,
                "📅 You have no upcoming sessions booked.\n"
                "💜 Would you like to book your next class?",
                label="client_bookings_none",
            )
            return

        lines = ["📅 *Your upcoming sessions:*"]
        for s in sessions[:5]:
            d = s.get("date")
            t = s.get("time")
            stype = s.get("session_type", "Session").capitalize()
            lines.append(f"• {d} {t} — {stype}")

        msg = "\n".join(lines)
        safe_execute(send_whatsapp_text, wa_number, msg, label="client_bookings_ok")

    except Exception as e:
        log.error(f"[show_bookings] Failed: {e}")
        safe_execute(
            send_whatsapp_text,
            wa_number,
            "⚠ Sorry, I couldn’t fetch your bookings right now. Please try again shortly.",
            label="client_bookings_error",
        )


# ───────────────────────────────────────────────
# 🔹 Cancel next session
# ───────────────────────────────────────────────
def cancel_next(wa_number: str):
    """Cancel the next confirmed booking for the client."""
    try:
        payload = {"action": "cancel_next", "wa": wa_number}
        res = requests.post(APPS_SCRIPT_URL, json=payload, timeout=15)
        data = res.json() if res.status_code == 200 else {}

        if not data.get("ok"):
            safe_execute(
                send_whatsapp_text,
                wa_number,
                "⚠ You have no upcoming bookings to cancel.",
                label="client_cancel_none",
            )
            return

        dt_str = data.get("cancelled_session", "your next session")
        safe_execute(
            send_whatsapp_text,
            wa_number,
            f"❌ Your next session on {dt_str} has been cancelled.",
            label="client_cancel_next",
        )

    except Exception as e:
        log.error(f"[cancel_next] Error: {e}")
        safe_execute(
            send_whatsapp_text,
            wa_number,
            "⚠ I couldn’t update your booking. Please try again or contact Nadine.",
            label="client_cancel_next_error",
        )


# ───────────────────────────────────────────────
# 🔹 Cancel by day and time
# ───────────────────────────────────────────────
def cancel_specific(wa_number: str, day: str, time: str):
    """Cancel a specific session by weekday and time."""
    try:
        payload = {"action": "cancel_by_date_time", "wa": wa_number, "day": day, "time": time}
        res = requests.post(APPS_SCRIPT_URL, json=payload, timeout=15)
        data = res.json() if res.status_code == 200 else {}

        if not data.get("ok"):
            safe_execute(
                send_whatsapp_text,
                wa_number,
                f"⚠ Could not find a booking for {day} at {time}.",
                label="client_cancel_specific_fail",
            )
            return

        safe_execute(
            send_whatsapp_text,
            wa_number,
            f"❌ Your session on {day} at {time} has been cancelled.",
            label="client_cancel_specific_ok",
        )

    except Exception as e:
        log.error(f"[cancel_specific] Error: {e}")
        safe_execute(
            send_whatsapp_text,
            wa_number,
            "⚠ Sorry, something went wrong while cancelling. Please try again later.",
            label="client_cancel_specific_error",
        )
