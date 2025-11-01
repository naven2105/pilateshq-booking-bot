"""
client_reschedule_handler.py – Phase 25A (Unified Reschedule Logic)
────────────────────────────────────────────────────────────
Handles all reschedule events triggered by WhatsApp messages.

✅ Scenarios Covered
 • Client sends "reschedule", "cancel", "can't make", etc. → marks as rescheduled (source=client)
 • Nadine sends "reschedule {client}"                     → marks as rescheduled (source=admin)
 • Nadine sends "{client} noshow"                         → marks as no-show   (source=noshow)

✅ Features
 • Duplicate-prevention within the same run
 • Retry-once logic for transient network errors
 • Notifies Nadine of success/failure
 • Posts structured payloads to GAS_ATTENDANCE_URL or GAS_SCHEDULE_URL
────────────────────────────────────────────────────────────
"""

import os
import time
import logging
import requests
from .utils import send_safe_message

log = logging.getLogger(__name__)

# ── Environment setup ─────────────────────────────────────────────
NADINE_WA = os.getenv("NADINE_WA", "")
GAS_ATTENDANCE_URL = os.getenv("GAS_ATTENDANCE_URL", "")
GAS_SCHEDULE_URL = os.getenv("GAS_SCHEDULE_URL", "")
WEBHOOK_BASE = os.getenv("WEBHOOK_BASE", "https://pilateshq-booking-bot.onrender.com")

_seen_clients = set()  # in-memory duplicate prevention


# ─────────────────────────────────────────────────────────────────────
def _post_to_gas(payload: dict):
    """Internal helper to send POST → GAS, retry once."""
    url = GAS_ATTENDANCE_URL or GAS_SCHEDULE_URL
    if not url:
        return {"ok": False, "error": "Missing GAS_ATTENDANCE_URL or GAS_SCHEDULE_URL"}

    for attempt in range(2):
        try:
            r = requests.post(url, json=payload, timeout=10)
            if r.ok:
                data = r.json()
                if data.get("ok"):
                    return {"ok": True, "data": data}
                else:
                    return {"ok": False, "error": data.get("error", "Unknown GAS error")}
            else:
                log.warning(f"GAS returned HTTP {r.status_code}")
        except Exception as e:
            log.warning(f"GAS request failed (attempt {attempt+1}): {e}")
        time.sleep(1.2)

    return {"ok": False, "error": "GAS request timeout"}


# ─────────────────────────────────────────────────────────────────────
def handle_reschedule_event(profile_name: str, wa_number: str, msg_text: str, is_admin: bool = False):
    """
    Unified entry point for all reschedule-related messages.
    Returns Flask-style JSON dict and HTTP code.
    """
    lower = msg_text.lower().strip()
    client_name = profile_name

    # ── Determine scenario ─────────────────────────────────────────────
    if is_admin and "noshow" in lower:
        action_type = "noshow"
        try:
            client_name = msg_text.replace("noshow", "").strip()
        except Exception:
            pass
    elif is_admin and lower.startswith("reschedule "):
        action_type = "reschedule"
        client_name = msg_text.split(" ", 1)[1].strip()
    elif is_admin and lower == "reschedule":
        # fallback for just "reschedule" from Nadine
        action_type = "reschedule"
    else:
        action_type = "reschedule"  # default for clients

    if not client_name:
        client_name = profile_name or "Unknown"

    # ── Duplicate prevention ──────────────────────────────────────────
    key = f"{client_name.lower()}:{action_type}"
    if key in _seen_clients:
        log.info(f"⏩ Duplicate ignored: {key}")
        return {"ok": True, "message": f"Duplicate {action_type} ignored"}, 200
    _seen_clients.add(key)

    # ── Prepare GAS payload ────────────────────────────────────────────
    payload = {
        "action": "mark_reschedule",
        "client_name": client_name,
        "source": "admin" if is_admin else "client",
        "type": action_type
    }
    log.info(f"🔁 Posting to GAS: {payload}")

    result = _post_to_gas(payload)
    ok = result.get("ok", False)
    error = result.get("error", "")
    msg = f"✅ {action_type.capitalize()} logged for {client_name}" if ok else f"⚠️ Failed to log {action_type} for {client_name}: {error}"

    # ── Notify Nadine (always) ─────────────────────────────────────────
    try:
        send_safe_message(NADINE_WA, msg)
    except Exception as e:
        log.error(f"⚠️ Failed to notify admin: {e}")

    return {"ok": ok, "message": msg}, (200 if ok else 502)
