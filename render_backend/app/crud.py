"""
crud.py
──────────────────────────────
Google Sheets-based CRUD adapter for PilatesHQ chatbot.
Replaces SQLAlchemy models with webhook and sheet integration.

All operations now use:
 - Sessions sheet (sessions)
 - Clients sheet (clients)
 - Packages sheet (packages)
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import requests
from .utils import normalize_wa
from .config import WEBHOOK_BASE, TIMEZONE

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Legacy-safe webhook helper
# ──────────────────────────────────────────────
def post_to_webhook(url: str, payload: dict) -> dict:
    """
    Legacy compatibility helper to post JSON payloads to Google Apps Script or webhook endpoints.
    Returns parsed JSON or an {ok: False} fallback on error.
    """
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.ok:
            return r.json()
        log.warning(f"⚠️ post_to_webhook: {url} returned {r.status_code}")
        return {"ok": False, "status": r.status_code, "text": r.text}
    except Exception as e:
        log.error(f"❌ post_to_webhook failed: {e}")
        return {"ok": False, "error": str(e)}


# ──────────────────────────────────────────────
# Utility Helpers
# ──────────────────────────────────────────────
def _today():
    return datetime.now().strftime("%Y-%m-%d")

def _date_range(days: int = 7):
    start = datetime.now()
    end = start + timedelta(days=days)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


# ──────────────────────────────────────────────
# Client-Facing Queries
# ──────────────────────────────────────────────
def get_next_lesson(wa_number: str) -> Optional[Dict]:
    """Return the next confirmed session for the given client (by WA number)."""
    try:
        wa = normalize_wa(wa_number)
        res = post_to_webhook(f"{WEBHOOK_BASE}/sheets", {"action": "get_sessions"})
        sessions = res.get("sessions", []) if isinstance(res, dict) else []

        today = datetime.now()
        upcoming = []
        for s in sessions:
            if normalize_wa(s.get("wa_number", "")) == wa and s.get("status", "").lower() == "confirmed":
                sdate = datetime.strptime(s.get("session_date"), "%Y-%m-%d")
                if sdate >= today:
                    upcoming.append(s)

        if not upcoming:
            return None

        upcoming.sort(key=lambda x: (x["session_date"], x["start_time"]))
        next_s = upcoming[0]
        return {
            "date": next_s["session_date"],
            "time": next_s["start_time"],
            "type": next_s.get("session_type", ""),
            "status": next_s.get("status", "confirmed"),
        }
    except Exception as e:
        log.error(f"❌ Error fetching next lesson: {e}")
        return None


def get_sessions_this_week(wa_number: str) -> List[Dict]:
    """Return all confirmed sessions for next 7 days."""
    start, end = _date_range(7)
    try:
        wa = normalize_wa(wa_number)
        res = post_to_webhook(f"{WEBHOOK_BASE}/sheets", {"action": "get_sessions"})
        sessions = res.get("sessions", []) if isinstance(res, dict) else []

        out = []
        for s in sessions:
            if normalize_wa(s.get("wa_number", "")) == wa and s.get("status", "").lower() == "confirmed":
                date_str = s.get("session_date")
                if start <= date_str <= end:
                    out.append({
                        "date": date_str,
                        "time": s.get("start_time"),
                        "type": s.get("session_type", ""),
                    })
        return sorted(out, key=lambda x: (x["date"], x["time"]))
    except Exception as e:
        log.error(f"❌ Error fetching weekly sessions: {e}")
        return []


def cancel_next_lesson(wa_number: str) -> bool:
    """Cancel the next confirmed session for the client (via webhook update)."""
    try:
        next_lesson = get_next_lesson(wa_number)
        if not next_lesson:
            return False

        payload = {
            "action": "cancel_by_date_time",
            "wa": wa_number,
            "day": next_lesson["date"],
            "time": next_lesson["time"],
        }
        res = post_to_webhook(f"{WEBHOOK_BASE}/sheets", payload)
        ok = res.get("ok", False)
        log.info(f"[cancel_next_lesson] {wa_number} → {next_lesson['date']} {next_lesson['time']} ok={ok}")
        return ok
    except Exception as e:
        log.error(f"❌ Error cancelling next lesson: {e}")
        return False


# ──────────────────────────────────────────────
# Admin / Reporting Queries
# ──────────────────────────────────────────────
def get_weekly_schedule() -> List[Dict]:
    """Return next 7 days of sessions."""
    start, end = _date_range(7)
    try:
        res = post_to_webhook(f"{WEBHOOK_BASE}/sheets", {"action": "get_sessions"})
        sessions = res.get("sessions", []) if isinstance(res, dict) else []

        return [
            {
                "date": s.get("session_date"),
                "time": s.get("start_time"),
                "client": s.get("client_name"),
                "type": s.get("session_type"),
                "status": s.get("status"),
            }
            for s in sessions
            if start <= s.get("session_date") <= end
        ]
    except Exception as e:
        log.error(f"❌ Error fetching weekly schedule: {e}")
        return []


def get_client_sessions_for_month(wa_number: str, year: int, month: int) -> List[Dict]:
    """Get all confirmed sessions for a client in a given month."""
    try:
        wa = normalize_wa(wa_number)
        res = post_to_webhook(f"{WEBHOOK_BASE}/sheets", {"action": "get_sessions"})
        sessions = res.get("sessions", []) if isinstance(res, dict) else []

        out = []
        for s in sessions:
            if normalize_wa(s.get("wa_number", "")) == wa and s.get("status", "").lower() == "confirmed":
                sdate = s.get("session_date")
                if sdate.startswith(f"{year}-{month:02d}"):
                    out.append({
                        "date": sdate,
                        "time": s.get("start_time"),
                        "type": s.get("session_type", ""),
                    })
        return sorted(out, key=lambda x: (x["date"], x["time"]))
    except Exception as e:
        log.error(f"❌ Error fetching client month sessions: {e}")
        return []


def get_cancellations_today() -> List[Dict]:
    """Return today's cancellations."""
    try:
        today = _today()
        res = post_to_webhook(f"{WEBHOOK_BASE}/sheets", {"action": "get_sessions"})
        sessions = res.get("sessions", []) if isinstance(res, dict) else []

        return [
            {
                "client": s.get("client_name"),
                "date": s.get("session_date"),
                "time": s.get("start_time"),
            }
            for s in sessions
            if s.get("session_date") == today and (s.get("status", "").lower() == "cancelled")
        ]
    except Exception as e:
        log.error(f"❌ Error fetching cancellations: {e}")
        return []


def get_clients_without_bookings_this_week() -> List[str]:
    """List clients who have no confirmed sessions this week."""
    try:
        start, end = _date_range(7)
        res_clients = post_to_webhook(f"{WEBHOOK_BASE}/sheets", {"action": "get_clients"})
        clients = res_clients.get("clients", []) if isinstance(res_clients, dict) else []

        res_sessions = post_to_webhook(f"{WEBHOOK_BASE}/sheets", {"action": "get_sessions"})
        sessions = res_sessions.get("sessions", []) if isinstance(res_sessions, dict) else []

        booked = {
            normalize_wa(s.get("wa_number", ""))
            for s in sessions
            if start <= s.get("session_date") <= end and s.get("status", "").lower() == "confirmed"
        }

        unbooked = [c.get("name") for c in clients if normalize_wa(c.get("phone", "")) not in booked]
        return unbooked
    except Exception as e:
        log.error(f"❌ Error fetching unbooked clients: {e}")
        return []


def get_weekly_recap() -> List[Dict]:
    """Return attendance recap for the past 7 days."""
    try:
        today = datetime.now()
        last_week = today - timedelta(days=7)
        res = post_to_webhook(f"{WEBHOOK_BASE}/sheets", {"action": "get_sessions"})
        sessions = res.get("sessions", []) if isinstance(res, dict) else []

        past = [
            s for s in sessions
            if last_week.strftime("%Y-%m-%d") <= s.get("session_date", "") <= today.strftime("%Y-%m-%d")
        ]
        grouped = {}
        for s in past:
            key = (s.get("session_date"), s.get("start_time"))
            grouped.setdefault(key, 0)
            grouped[key] += 1

        return [
            {"date": d, "time": t, "count": c}
            for (d, t), c in sorted(grouped.items())
        ]
    except Exception as e:
        log.error(f"❌ Error building weekly recap: {e}")
        return []
