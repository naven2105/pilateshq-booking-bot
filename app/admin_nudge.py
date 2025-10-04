"""
admin_nudge.py
──────────────
Handles admin notifications (nudges) to Nadine for:
 - New prospects
 - Booking updates
 - Attendance issues (sick, no-show, cancel)
 - Deactivation requests/confirmations
"""

import logging
from datetime import datetime
from .utils import safe_execute, send_whatsapp_template
from .db import get_session
from sqlalchemy import text
import os
import re

log = logging.getLogger(__name__)

# Nadine's WhatsApp number from env
NADINE_WA = os.getenv("NADINE_WA", "")

# Approved Meta template for new lead alerts
ADMIN_NEW_LEAD_TEMPLATE = "admin_new_lead_alert"
TEMPLATE_LANG = os.getenv("TEMPLATE_LANG", "en_US")


def _log_notification(label: str, msg: str):
    """Insert admin notification into notifications_log for audit trail."""
    with get_session() as s:
        s.execute(
            text(
                "INSERT INTO notifications_log (label, message, created_at) "
                "VALUES (:l, :m, :ts)"
            ),
            {"l": label, "m": msg, "ts": datetime.now()},
        )
    log.info(f"[ADMIN NUDGE] {label}: {msg}")


def _format_dob(dob: str | None) -> str | None:
    """Format DOB for display. Hide year if it's the dummy 1900."""
    if not dob:
        return None
    try:
        dt = datetime.fromisoformat(dob)
        if dt.year == 1900:
            return f"{dt.day:02d}-{dt.month:02d}"  # show only DD-MM
        return dt.strftime("%d-%m-%Y")
    except Exception:
        return dob


def _sanitize_param(text: str) -> str:
    """
    Meta template vars cannot contain newlines, tabs, or >4 spaces.
    This helper flattens and cleans text.
    """
    if not text:
        return ""
    # Replace newlines/tabs with spaces
    clean = re.sub(r"[\n\t]+", " ", text)
    # Collapse multiple spaces
    clean = re.sub(r"\s{2,}", " ", clean)
    return clean.strip()


# ── Prospect Alert (with Add Client button) ──
def prospect_alert(name: str, wa_number: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    body_text = _sanitize_param(f'{name} ({wa_number}) at {ts}')
    log.info(f"[ADMIN NUDGE] Prospect alert → {body_text}")

    # Use Meta-approved template with 1 variable
    safe_execute(
        send_whatsapp_template,
        NADINE_WA,
        ADMIN_NEW_LEAD_TEMPLATE,
        TEMPLATE_LANG,
        [body_text],   # fills {{1}}
        label="prospect_alert"
    )

    _log_notification("prospect_alert", body_text)


# ── Booking Update ──
def booking_update(name: str, session_type: str, day: str, time: str, dob: str | None = None, health: str | None = None):
    msg = (
        f"✅ Booking Added — {name} ({session_type.title()}), Recurring: {day} at {time}"
    )

    dob_fmt = _format_dob(dob)
    if dob_fmt:
        msg += f", DOB: {dob_fmt}"
    if health:
        msg += f", Health: {health}"

    msg = _sanitize_param(msg)

    safe_execute(
        send_whatsapp_template,
        NADINE_WA,
        "admin_update_us",
        TEMPLATE_LANG,
        [msg],
        label="booking_update"
    )
    _log_notification("booking_update", msg)


# ── Attendance Status ──
def status_update(name: str, status: str):
    msg = _sanitize_param(f"⚠️ {name} marked as {status.upper()} today.")
    safe_execute(
        send_whatsapp_template,
        NADINE_WA,
        "admin_update_us",
        TEMPLATE_LANG,
        [msg],
        label="status_update"
    )
    _log_notification("status_update", msg)


# ── Deactivation ──
def request_deactivate(name: str, wa: str):
    msg = _sanitize_param(f"❔ Deactivation requested for {name}. Confirm?")
    safe_execute(
        send_whatsapp_template,
        NADINE_WA,
        "admin_update_us",
        TEMPLATE_LANG,
        [msg],
        label="request_deactivate"
    )
    _log_notification("request_deactivate", msg)


def confirm_deactivate(name: str, wa: str):
    msg = _sanitize_param(f"✅ Client {name} has been deactivated.")
    safe_execute(
        send_whatsapp_template,
        NADINE_WA,
        "admin_update_us",
        TEMPLATE_LANG,
        [msg],
        label="confirm_deactivate"
    )
    _log_notification("confirm_deactivate", msg)
