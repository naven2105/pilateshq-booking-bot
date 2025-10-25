"""
admin_reminders.py
────────────────────────────────────────────
Generates daily admin summaries from Google Sheets.

Notes:
 • All time-based triggers (06h00 morning brief, 20h00 preview)
   are executed in Google Apps Script.
 • Render backend exposes callable functions only — no CRON.

Sends WhatsApp template messages:
 - Morning summary (06h00 via GAS)
 - Evening preview (20h00 via GAS)
────────────────────────────────────────────
"""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import List, Dict
from .config import ADMIN_NUMBERS, WEBHOOK_BASE
from . import utils

log = logging.getLogger(__name__)
TZ = ZoneInfo("Africa/Johannesburg")

def _fetch_sessions(target_date: datetime.date) -> Dict[str, List[str]]:
    """Fetch confirmed sessions for the given date from Google Sheets."""
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
    if not by_hour:
        return "No sessions scheduled."
    parts = [f"{hhmm}({len(names)}): {', '.join(names)}" for hhmm, names in sorted(by_hour.items())]
    return " • ".join(parts)

def _send_to_admins(tpl_name: str, count: int, details: str, context_label: str) -> int:
    sent_ok = 0
    log.info(f"[{context_label}] Using template {tpl_name}")
    for admin in ADMIN_NUMBERS:
        resp = utils.send_whatsapp_template(admin, tpl_name, "en_US", [str(count), details])
        if resp.get("ok"):
            sent_ok += 1
        else:
            body = f"PilatesHQ {context_label}\nTotal sessions: {count}\n{details}"
            utils.send_whatsapp_text(admin, body)
            log.error(f"[{context_label}][FALLBACK] Template {tpl_name} failed → plain text sent to {admin}")
    return sent_ok

def run_admin_morning() -> int:
    today = datetime.now(TZ).date()
    by_hour = _fetch_sessions(today)
    return _send_to_admins("admin_morning_us", len(by_hour), _format_admin_summary_line(by_hour), "admin-morning")

def run_admin_daily() -> int:
    tomorrow = datetime.now(TZ).date() + timedelta(days=1)
    by_hour = _fetch_sessions(tomorrow)
    return _send_to_admins("admin_20h00_us", len(by_hour), _format_admin_summary_line(by_hour), "admin-daily")
