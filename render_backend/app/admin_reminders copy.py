#app/admin_reminders
"""
admin_reminders.py
────────────────────────────────────────────
Generates daily admin summaries from Google Sheets.

Replaces SQL lookups with webhook integration (Sheets backend).
Sends WhatsApp template messages:
 - Morning summary (06h00)
 - Evening preview (20h00)
"""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import List, Dict

from .config import ADMIN_NUMBERS, WEBHOOK_BASE
from . import utils

log = logging.getLogger(__name__)
TZ = ZoneInfo("Africa/Johannesburg")


# ───────────────────────────────────────────────
# Helpers (fetch + format)
# ───────────────────────────────────────────────
def _fetch_sessions(target_date: datetime.date) -> Dict[str, List[str]]:
    """
    Fetch confirmed sessions for the given date from Google Sheets.
    Returns dict { 'HH:MM': ['Client1', 'Client2', ...] }.
    """
    try:
        payload = {"action": "get_sessions"}
        res = utils.post_to_webhook(f"{WEBHOOK_BASE}/sheets", payload)
        rows = res.get("sessions", []) if isinstance(res, dict) else []

        by_hour: Dict[str, List[str]] = {}
        date_str = target_date.strftime("%Y-%m-%d")

        for row in rows:
            session_date = row.get("session_date")
            time = row.get("start_time")
            client = row.get("client_name")
            status = (row.get("status") or "").lower()

            if session_date == date_str and status == "confirmed":
                by_hour.setdefault(time, []).append(client)

        return by_hour

    except Exception as e:
        log.error(f"❌ Error fetching sessions for {target_date}: {e}")
        return {}


def _format_admin_summary_line(by_hour: Dict[str, List[str]]) -> str:
    """Format into compact summary text."""
    if not by_hour:
        return "No sessions scheduled."
    parts: List[str] = []
    for hhmm in sorted(by_hour.keys()):
        names = by_hour[hhmm]
        parts.append(f"{hhmm}({len(names)}): {', '.join(names)}")
    return " • ".join(parts)


def _send_to_admins(tpl_name: str, count: int, details: str, context_label: str) -> int:
    """Send WhatsApp templates to all admins, fallback to text."""
    sent_ok = 0
    log.info(f"[{context_label}] Using template {tpl_name}")

    for admin in ADMIN_NUMBERS:
        resp = utils.send_whatsapp_template(
            admin,
            tpl_name,
            "en_US",
            [str(count), details],
        )
        ok = bool(resp.get("ok"))
        status = resp.get("status_code")

        log.info(
            "[%s][send] to=%s tpl=%s status=%s ok=%s count=%s",
            context_label, admin, tpl_name, status, ok, count
        )

        if ok:
            sent_ok += 1
        else:
            body = f"PilatesHQ {context_label}\nTotal sessions: {count}\n{details}"
            utils.send_whatsapp_text(admin, body)
            log.error(
                "[%s][FALLBACK] Template %s failed → plain text sent to %s",
                context_label, tpl_name, admin
            )

    return sent_ok


# ───────────────────────────────────────────────
# Main jobs
# ───────────────────────────────────────────────
def run_admin_morning() -> int:
    """06:00 SAST morning brief using 'admin_morning_us' template."""
    today = datetime.now(TZ).date()
    by_hour = _fetch_sessions(today)
    details = _format_admin_summary_line(by_hour)
    count = len(by_hour)
    return _send_to_admins("admin_morning_us", count, details, "admin-morning")


def run_admin_daily() -> int:
    """20:00 SAST evening preview using 'admin_20h00_us' template."""
    tomorrow = datetime.now(TZ).date() + timedelta(days=1)
    by_hour = _fetch_sessions(tomorrow)
    details = _format_admin_summary_line(by_hour)
    count = len(by_hour)
    return _send_to_admins("admin_20h00_us", count, details, "admin-daily")
