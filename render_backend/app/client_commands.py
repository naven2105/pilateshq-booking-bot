"""
client_commands.py – v2.1
──────────────────────────
Handles client booking queries (view, cancel, message Nadine),
now powered by Google Sheets instead of a SQL DB.

✅ Enhanced:
 - Automatically updates invoices whenever sessions are
   booked, confirmed, or cancelled.
 - Keeps invoices in sync with Sessions sheet in real-time.
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

TPL_ADMIN_ALERT = "admin_generic_alert_us"


# ───────────────────────────────────────────────────────────────
# Base Helpers
# ───────────────────────────────────────────────────────────────

def _fetch_sessions() -> List[List[str]]:
    """Fetch all rows from Sessions sheet."""
    try:
        r = requests.get(SHEET_READ_URL, timeout=12)
        r.raise_for_status()
        return r.json().get("values", [])
    except Exception as e:
        log.error(f"❌ fetch sessions failed: {e}")
        return []


def _rows_for_wa(wa_number: str) -> List[Dict]:
    """Return session rows belonging to this wa_number."""
    wa = normalize_wa(wa_number)
    values = _fetch_sessions()
    if not values:
        return []
    header, rows = values[0], values[1:]
    out: List[Dict] = []
    for i, r in enumerate(rows, start=2):
        r = (r + [""] * 9)[:9]
        sdate, stime, cname, wa_raw, stype, status, notes, sent_at, pkg_id = r
        if normalize_wa(wa_raw) != wa:
            continue
        try:
            d_obj = datetime.strptime(sdate, "%Y-%m-%d").date()
            t_obj = datetime.strptime(stime, "%H:%M").time()
        except Exception:
            continue
        out.append({
            "row_index": i,
            "date": d_obj,
            "time": t_obj,
            "client_name": cname,
            "wa": normalize_wa(wa_raw),
            "type": (stype or "").strip().lower(),
            "status": (status or "").strip().lower(),
            "notes": notes or "",
            "pkg_id": pkg_id or "",
        })
    return out


def _fmt_day(d: date) -> str: return d.strftime("%a %d %b")
def _fmt_time(t: dtime) -> str: return t.strftime("%H:%M")


def _normalize_time_str(s: str) -> Optional[str]:
    """Accepts '08:00', '8h00', '8', etc. → returns 'HH:MM'."""
    txt = (s or "").strip().lower().replace(" ", "")
    import re
    m = re.fullmatch(r"(\d{1,2})h(\d{2})", txt)
    if m:
        return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"
    m = re.fullmatch(r"(\d{1,2})h", txt)
    if m:
        return f"{int(m.group(1)):02d}:00"
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?$", txt)
    if m:
        hh = int(m.group(1))
        mm = int(m.group(2) or 0)
        return f"{hh:02d}:{mm:02d}"
    if re.fullmatch(r"\d{1,2}:\d{2}", txt):
        hh, mm = txt.split(":")
        return f"{int(hh):02d}:{int(mm):02d}"
    return None


def _post_apps_script(payload: dict) -> bool:
    """Generic POST to Apps Script doPost."""
    if not APPS_SCRIPT_URL:
        log.warning("⚠️ APPS_SCRIPT_URL not configured.")
        return False
    try:
        res = requests.post(APPS_SCRIPT_URL, json=payload, timeout=12)
        log.info(f"[AppsScript] POST {payload.get('action')} → {res.status_code}")
        return 200 <= res.status_code < 300
    except Exception as e:
        log.error(f"❌ AppsScript post failed: {e}")
        return False


def _notify_admin_text(message: str):
    """Notify Nadine via WhatsApp template."""
    if NADINE_WA:
        safe_execute(
            send_whatsapp_template,
            NADINE_WA,
            "admin_generic_alert_us",
            TEMPLATE_LANG or "en_US",
            [message],
            label="notify_admin",
        )


# ───────────────────────────────────────────────────────────────
# 🔄 Invoice Auto-Refresh Helper
# ───────────────────────────────────────────────────────────────
def _update_invoice_for_client(client_name: str):
    """Tell Apps Script to refresh this client’s invoice from Sessions."""
    if not APPS_SCRIPT_URL or not client_name:
        return
    try:
        payload = {"action": "upsert_from_sessions", "client_name": client_name}
        res = requests.post(APPS_SCRIPT_URL, json=payload, timeout=10)
        if res.ok:
            log.info(f"[Invoice Update] {client_name} → OK")
        else:
            log.warning(f"[Invoice Update] {client_name} failed: {res.text[:120]}")
    except Exception as e:
        log.warning(f"Invoice update failed for {client_name}: {e}")


# ───────────────────────────────────────────────────────────────
# Public Commands
# ───────────────────────────────────────────────────────────────

def show_bookings(wa_number: str):
    """Show upcoming sessions for a client."""
    rows = _rows_for_wa(wa_number)
    today = date.today()
    upcoming = [r for r in rows if r["status"] == "confirmed" and r["date"] >= today]
    upcoming.sort(key=lambda r: (r["date"], r["time"]))
    upcoming = upcoming[:5]

    if not upcoming:
        safe_execute(
            send_whatsapp_text,
            wa_number,
            "📅 You have no upcoming sessions booked.\n💜 Would you like to book your next class?",
            label="client_bookings_none",
        )
        return

    lines = ["📅 Your upcoming sessions:"]
    for r in upcoming:
        lines.append(f"• {_fmt_day(r['date'])} {_fmt_time(r['time'])} — {r['type'].capitalize()}")
    msg = "\n".join(lines)
    safe_execute(send_whatsapp_text, wa_number, msg, label="client_bookings_ok")


# ───────────────────────────────────────────────────────────────
# Booking Confirmation Hook (NEW)
# ───────────────────────────────────────────────────────────────
def confirm_booking(client_name: str, wa_number: str, session_str: str):
    """
    Called when Nadine confirms or books a session for a client.
    Example: 'Book Nadia Tue 10:00' or 'Confirm Fatima Wed 08h00'
    """
    msg = f"✅ {client_name}'s new booking confirmed: {session_str}"
    _notify_admin_text(msg)  # confirm to Nadine’s admin log
    safe_execute(
        send_whatsapp_text,
        wa_number,
        f"📅 Your booking is confirmed for {session_str}.",
        label="client_booking_confirmed",
    )
    # 🔄 Immediately refresh invoice
    _update_invoice_for_client(client_name)
    log.info(f"[Booking Confirmed] {client_name} → invoice updated.")


# ───────────────────────────────────────────────────────────────
# Cancellation Commands (unchanged + invoice refresh)
# ───────────────────────────────────────────────────────────────
def cancel_next(wa_number: str):
    """Cancel the next upcoming booking for the client."""
    rows = _rows_for_wa(wa_number)
    today = date.today()
    now_time = datetime.now().time()

    candidates = [
        r for r in rows if r["status"] == "confirmed" and
        (r["date"] > today or (r["date"] == today and r["time"] >= now_time))
    ]
    if not candidates:
        safe_execute(send_whatsapp_text, wa_number, "⚠ You have no upcoming bookings to cancel.", label="client_cancel_none")
        return

    nxt = sorted(candidates, key=lambda r: (r["date"], r["time"]))[0]
    dt_str = f"{_fmt_day(nxt['date'])} at {_fmt_time(nxt['time'])}"
    ok = _post_apps_script({"action": "cancel_by_row", "rowIndex": nxt["row_index"]})

    if ok:
        safe_execute(send_whatsapp_text, wa_number, f"❌ Your next session on {dt_str} has been cancelled.", label="client_cancel_next_ok")
        _notify_admin_text(f"❌ Client {wa_number} cancelled their next session on {dt_str}.")
        _update_invoice_for_client(nxt["client_name"])  # 🔄
    else:
        safe_execute(send_whatsapp_text, wa_number, f"⚠ Could not cancel your session on {dt_str}. Nadine will assist shortly.", label="client_cancel_next_fail")
        _notify_admin_text(f"⚠ Cancel request FAILED for {wa_number} on {dt_str}.")


def cancel_specific(wa_number: str, day: str, time_str: str):
    """Cancel a specific session by weekday & time."""
    rows = _rows_for_wa(wa_number)
    today = date.today()
    target_hhmm = _normalize_time_str(time_str)
    if not target_hhmm:
        safe_execute(send_whatsapp_text, wa_number, "⚠ Please use a time like 08:00 or 08h00.", label="client_cancel_specific_badtime")
        return

    target_day = (day or "").strip().lower()[:3]
    matches = [
        r for r in rows
        if r["status"] == "confirmed"
        and _fmt_time(r["time"]) == target_hhmm
        and _fmt_day(r["date"]).lower().startswith(target_day)
        and r["date"] >= today
    ]
    if not matches:
        safe_execute(send_whatsapp_text, wa_number, f"⚠ Could not find a booking for {day} at {target_hhmm}.", label="client_cancel_specific_none")
        return

    tgt = sorted(matches, key=lambda r: (r["date"], r["time"]))[0]
    dt_str = f"{_fmt_day(tgt['date'])} at {_fmt_time(tgt['time'])}"
    ok = _post_apps_script({"action": "cancel_by_row", "rowIndex": tgt["row_index"]})
    if ok:
        safe_execute(send_whatsapp_text, wa_number, f"❌ Your session on {dt_str} has been cancelled.", label="client_cancel_specific_ok")
        _notify_admin_text(f"❌ Client {wa_number} cancelled session on {dt_str}.")
        _update_invoice_for_client(tgt["client_name"])  # 🔄
    else:
        safe_execute(send_whatsapp_text, wa_number, f"⚠ Could not cancel your session on {dt_str}. Nadine will assist shortly.", label="client_cancel_specific_fail")
        _notify_admin_text(f"⚠ Cancel request FAILED for {wa_number} on {dt_str}.")


# ───────────────────────────────────────────────────────────────
# Message Forwarding
# ───────────────────────────────────────────────────────────────
def message_nadine(wa_number: str, cname: str, msg: str):
    """Send a free-text message from a client to Nadine."""
    if not (msg or "").strip():
        safe_execute(send_whatsapp_text, wa_number, "⚠ Please include a message after 'message Nadine'.", label="client_message_fail")
        return
    safe_execute(send_whatsapp_text, wa_number, "💜 Your message has been sent to Nadine. She’ll get back to you soon.", label="client_message_ack")
    body = f"📩 Message from {cname or 'Client'} ({normalize_wa(wa_number)}):\n\n{msg}"
    safe_execute(send_whatsapp_template, NADINE_WA, TPL_ADMIN_ALERT, TEMPLATE_LANG or "en_US", [body], label="admin_forward_msg")
