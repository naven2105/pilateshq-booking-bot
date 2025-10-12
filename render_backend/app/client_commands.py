#app/client_commands.py
"""
client_commands.py
──────────────────
Handles client booking queries (view, cancel, message Nadine),
now powered by Google Sheets instead of a SQL DB.

Sheets:
  Sessions!A:I
    A=session_date (YYYY-MM-DD)
    B=start_time  (HH:MM)
    C=client_name
    D=wa_number (digits-only or +27…)
    E=session_type (single/duo/group)
    F=status (confirmed/cancelled/…)
    G=notes
    H=reminder_sent_at
    I=package_id
"""

from __future__ import annotations
import logging
import os
import requests
from datetime import datetime, date, time as dtime
from typing import List, Dict, Optional

from .utils import (
    send_whatsapp_text,
    send_whatsapp_template,
    normalize_wa,
    safe_execute,
)
from .config import NADINE_WA, TEMPLATE_LANG

log = logging.getLogger(__name__)

# ── Config (env) ───────────────────────────────────────────────
SHEET_ID = os.getenv("CLIENT_SHEET_ID", os.getenv("SHEET_ID", ""))
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
APPS_SCRIPT_URL = os.getenv("APPS_SCRIPT_URL", "")

if not SHEET_ID:
    log.warning("[client_commands] SHEET_ID/CLIENT_SHEET_ID not configured.")
if not GOOGLE_API_KEY:
    log.warning("[client_commands] GOOGLE_API_KEY not configured.")

SESSIONS_RANGE = "Sessions!A:I"
SHEET_READ_URL = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/{SESSIONS_RANGE}?key={GOOGLE_API_KEY}"

# WhatsApp template for admin alerts
TPL_ADMIN_ALERT = "admin_generic_alert_us"


# ── Helpers ───────────────────────────────────────────────────

def _fetch_sessions() -> List[List[str]]:
    """Fetch all rows (including header) from Sessions sheet."""
    try:
        r = requests.get(SHEET_READ_URL, timeout=12)
        r.raise_for_status()
        values = r.json().get("values", [])
        return values
    except Exception as e:
        log.error(f"❌ fetch sessions failed: {e}")
        return []


def _rows_for_wa(wa_number: str) -> List[Dict]:
    """
    Return session rows belonging to this wa_number, with parsed fields and 1-based row_index.
    """
    wa = normalize_wa(wa_number)
    values = _fetch_sessions()
    if not values:
        return []
    header, rows = values[0], values[1:]
    out: List[Dict] = []
    for i, r in enumerate(rows, start=2):  # 1-based index; +1 for header
        # Pad row for missing cells
        r = (r + [""] * 9)[:9]
        sdate, stime, cname, wa_raw, stype, status, notes, sent_at, pkg_id = r
        wa_row = normalize_wa(wa_raw)
        if wa_row != wa:
            continue
        # Parse date/time
        try:
            d_obj = datetime.strptime(sdate, "%Y-%m-%d").date()
        except Exception:
            continue
        try:
            t_obj = datetime.strptime(stime, "%H:%M").time()
        except Exception:
            # allow H:MM (e.g. "8:00")
            try:
                t_obj = datetime.strptime(stime, "%H:%M").time()
            except Exception:
                continue

        out.append({
            "row_index": i,          # Sheets row (1-based)
            "date": d_obj,           # datetime.date
            "time": t_obj,           # datetime.time
            "client_name": cname,
            "wa": wa_row,
            "type": (stype or "").strip().lower(),   # single/duo/group
            "status": (status or "").strip().lower(),
            "notes": notes or "",
            "pkg_id": pkg_id or "",
        })
    return out


def _fmt_day(d: date) -> str:
    return d.strftime("%a %d %b")


def _fmt_time(t: dtime) -> str:
    return t.strftime("%H:%M")


def _normalize_time_str(s: str) -> Optional[str]:
    """
    Accepts '08:00', '8:00', '8', '08h00', '8h' → returns 'HH:MM' or None
    """
    txt = (s or "").strip().lower().replace(" ", "")
    # 08h30 / 8h / 8h00
    import re
    m = re.fullmatch(r"(\d{1,2})h(\d{2})", txt)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
        return f"{hh:02d}:{mm:02d}"
    m = re.fullmatch(r"(\d{1,2})h", txt)
    if m:
        hh = int(m.group(1))
        return f"{hh:02d}:00"
    # 9am / 9:30pm → keep 24h simple (assume no am/pm)
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?$", txt)
    if m:
        hh = int(m.group(1))
        mm = int(m.group(2) or 0)
        return f"{hh:02d}:{mm:02d}"
    # Already HH:MM?
    m = re.fullmatch(r"\d{1,2}:\d{2}", txt)
    if m:
        hh, mm = txt.split(":")
        return f"{int(hh):02d}:{int(mm):02d}"
    return None


def _weekday_prefix(d: date) -> str:
    # Returns e.g. 'Mon', 'Tue', ...
    return d.strftime("%a")


def _post_apps_script(payload: dict) -> bool:
    """
    Post to Apps Script doPost (write actions). Expects JSON body with action.
    Code.gs should handle:
      - { "action": "cancel_by_row", "rowIndex": 12 }
      - { "action": "cancel_by_date_time", "wa": "27...", "date": "YYYY-MM-DD", "time": "HH:MM" }
    """
    if not APPS_SCRIPT_URL:
        log.warning("⚠️ APPS_SCRIPT_URL not configured.")
        return False
    try:
        res = requests.post(APPS_SCRIPT_URL, json=payload, timeout=12)
        log.info(f"[AppsScript] POST {payload.get('action')} → {res.status_code} {res.text[:120]}")
        return 200 <= res.status_code < 300
    except Exception as e:
        log.error(f"❌ AppsScript post failed: {e}")
        return False


def _notify_admin_text(message: str):
    """Sends a simple admin alert to Nadine via template."""
    if not NADINE_WA:
        return
    safe_execute(
        send_whatsapp_template,
        NADINE_WA,
        "admin_generic_alert_us",
        TEMPLATE_LANG or "en_US",
        [message],
        label="notify_admin",
    )


# ── Public API (called from router) ───────────────────────────

def show_bookings(wa_number: str):
    """Show upcoming sessions for a client in a clean format (from Sheets)."""
    rows = _rows_for_wa(wa_number)
    today = date.today()

    upcoming = [
        r for r in rows
        if r["status"] == "confirmed" and r["date"] >= today
    ]
    upcoming.sort(key=lambda r: (r["date"], r["time"]))
    upcoming = upcoming[:5]

    if not upcoming:
        safe_execute(
            send_whatsapp_text,
            wa_number,
            "📅 You have no upcoming sessions booked.\n"
            "💜 Would you like to book your next class?",
            label="client_bookings_none",
        )
        return

    lines = ["📅 Your upcoming sessions:"]
    for r in upcoming:
        lines.append(f"• {_fmt_day(r['date'])} {_fmt_time(r['time'])} — {r['type'].capitalize()}")

    msg = "\n".join(lines)
    safe_execute(send_whatsapp_text, wa_number, msg, label="client_bookings_ok")


def cancel_next(wa_number: str):
    """Cancel the next upcoming booking for the client (via Apps Script)."""
    rows = _rows_for_wa(wa_number)
    today = date.today()
    now_time = datetime.now().time()

    # Next = earliest today (time >= now) or any future
    candidates = []
    for r in rows:
        if r["status"] != "confirmed":
            continue
        if r["date"] > today:
            candidates.append(r)
        elif r["date"] == today and r["time"] >= now_time:
            candidates.append(r)

    if not candidates:
        safe_execute(send_whatsapp_text, wa_number, "⚠ You have no upcoming bookings to cancel.", label="client_cancel_none")
        return

    nxt = sorted(candidates, key=lambda r: (r["date"], r["time"]))[0]

    ok = _post_apps_script({"action": "cancel_by_row", "rowIndex": nxt["row_index"]})
    dt_str = f"{_fmt_day(nxt['date'])} at {_fmt_time(nxt['time'])}"

    if ok:
        safe_execute(send_whatsapp_text, wa_number, f"❌ Your next session on {dt_str} has been cancelled.", label="client_cancel_next_ok")
        _notify_admin_text(f"❌ Client {wa_number} cancelled their next session on {dt_str}.")
    else:
        safe_execute(send_whatsapp_text, wa_number, f"⚠ Could not cancel your session on {dt_str}. Nadine will assist shortly.", label="client_cancel_next_fail")
        _notify_admin_text(f"⚠ Cancel request FAILED for {wa_number} on {dt_str}. Please review in the sheet.")


def cancel_specific(wa_number: str, day: str, time_str: str):
    """Cancel a specific session by weekday & time (HH:MM, HhMM accepted)."""
    rows = _rows_for_wa(wa_number)
    today = date.today()
    target_hhmm = _normalize_time_str(time_str)
    if not target_hhmm:
        safe_execute(send_whatsapp_text, wa_number, "⚠ Please use a time like 08:00 or 08h00.", label="client_cancel_specific_badtime")
        return

    # Find nearest future matching weekday+time
    target_day = (day or "").strip().lower()[:3]  # mon/tue/...
    matches = []
    for r in rows:
        if r["status"] != "confirmed":
            continue
        # weekday match
        if _weekday_prefix(r["date"]).lower().startswith(target_day):
            if _fmt_time(r["time"]) == target_hhmm and r["date"] >= today:
                matches.append(r)

    if not matches:
        safe_execute(send_whatsapp_text, wa_number, f"⚠ Could not find a booking for {day} at {target_hhmm}.", label="client_cancel_specific_none")
        return

    # Choose the earliest matching
    tgt = sorted(matches, key=lambda r: (r["date"], r["time"]))[0]
    dt_str = f"{_fmt_day(tgt['date'])} at {_fmt_time(tgt['time'])}"

    # Prefer row-index cancel (precise). Also provide a second API by date/time for flexibility.
    payload = {"action": "cancel_by_row", "rowIndex": tgt["row_index"]}
    ok = _post_apps_script(payload)
    if not ok:
        # fallback API (optional; add in code.gs if useful)
        ok = _post_apps_script({
            "action": "cancel_by_date_time",
            "wa": normalize_wa(wa_number),
            "date": tgt["date"].strftime("%Y-%m-%d"),
            "time": _fmt_time(tgt["time"]),
        })

    if ok:
        safe_execute(send_whatsapp_text, wa_number, f"❌ Your session on {dt_str} has been cancelled.", label="client_cancel_specific_ok")
        _notify_admin_text(f"❌ Client {wa_number} cancelled session on {dt_str}.")
    else:
        safe_execute(send_whatsapp_text, wa_number, f"⚠ Could not cancel your session on {dt_str}. Nadine will assist shortly.", label="client_cancel_specific_fail")
        _notify_admin_text(f"⚠ Cancel request FAILED for {wa_number} on {dt_str}. Please review in the sheet.")


def message_nadine(wa_number: str, cname: str, msg: str):
    """Send a free-text message from a client to Nadine."""
    if not (msg or "").strip():
        safe_execute(send_whatsapp_text, wa_number, "⚠ Please include a message after 'message Nadine'.", label="client_message_fail")
        return

    # Ack client
    safe_execute(send_whatsapp_text, wa_number, "💜 Your message has been sent to Nadine. She’ll get back to you soon.", label="client_message_ack")

    # Forward to Nadine
    body = f"📩 Message from {cname or 'Client'} ({normalize_wa(wa_number)}):\n\n{msg}"
    safe_execute(send_whatsapp_template, NADINE_WA, TPL_ADMIN_ALERT, TEMPLATE_LANG or "en_US", [body], label="admin_forward_msg")
