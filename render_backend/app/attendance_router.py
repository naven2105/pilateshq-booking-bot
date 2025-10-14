#app/attendance_router.py
"""
attendance_router.py
────────────────────────────────────────────
Handles client-initiated RESCHEDULE requests via WhatsApp.

Flow:
 - Client replies "RESCHEDULE"
 - System logs the request
 - Marks booking as 'pending_reschedule'
 - Sends Nadine an admin alert
 - Confirms to client that reschedule is noted

Routes:
 - /attendance/process   → POST webhook payload
────────────────────────────────────────────
"""

import logging
from flask import Blueprint, request, jsonify
from .utils import send_whatsapp_template
import os
import datetime

# ── Setup ─────────────────────────────────────────────
log = logging.getLogger(__name__)
bp = Blueprint("attendance_bp", __name__)

# ── Environment Variables ──────────────────────────────
NADINE_WA = os.getenv("NADINE_WA", "")
TEMPLATE_LANG = os.getenv("TEMPLATE_LANG", "en_US")

TPL_ADMIN_ALERT = "admin_generic_alert_us"
TPL_CLIENT_CONFIRM = "client_generic_alert_us"   # ✅ client confirmation
WEB_APP_URL = os.getenv("WEB_APP_URL", "")       # Optional Google Sheet sync

# ── Keyword Detection ─────────────────────────────────
RESCHEDULE_KEYWORDS = ["reschedule", "move", "change time", "another time", "later"]


# ── Helpers ───────────────────────────────────────────
def _notify_admin(client_name: str, wa_number: str):
    """Send Nadine an alert about the reschedule request."""
    msg = f"🔁 {client_name or wa_number} wants to reschedule their session."
    send_whatsapp_template(
        to=NADINE_WA,
        name=TPL_ADMIN_ALERT,
        lang=TEMPLATE_LANG,
        variables=[msg],
    )
    log.info(f"📲 Sent admin WhatsApp alert → {msg}")


def _notify_client(wa_number: str):
    """Send polite confirmation back to the client."""
    msg = "✅ Got it! Nadine will contact you to reschedule your session."
    send_whatsapp_template(
        to=wa_number,
        name=TPL_CLIENT_CONFIRM,
        lang=TEMPLATE_LANG,
        variables=[msg],
    )
    log.info(f"💬 Sent reschedule confirmation to client {wa_number}")


def _log_reschedule(wa_number: str, client_name: str = None):
    """Insert audit entry into attendance_log."""
    with get_session() as s:
        s.execute(
            text(
                """
                INSERT INTO attendance_log (wa_number, action, client_name, created_at)
                VALUES (:wa, 'pending_reschedule', :name, :ts)
                """
            ),
            {"wa": wa_number, "name": client_name, "ts": datetime.utcnow()},
        )
        s.commit()
    log.info(f"🗒️ Logged reschedule for {wa_number}")


def _update_booking_status(wa_number: str):
    """Mark the client’s latest upcoming booking as pending_reschedule."""
    with get_session() as s:
        result = s.execute(
            text(
                """
                UPDATE bookings
                SET status = 'pending_reschedule'
                WHERE client_id = (
                    SELECT id FROM clients WHERE wa_number = :wa LIMIT 1
                )
                AND session_id IN (
                    SELECT id FROM sessions WHERE session_date >= CURRENT_DATE
                )
                RETURNING id
                """
            ),
            {"wa": wa_number},
        )
        count = result.rowcount
        s.commit()
    log.info(f"🔄 Updated {count} booking(s) → pending_reschedule")
    return count


def _notify_script(wa_number: str):
    """Optional sync with Google Apps Script."""
    if not WEB_APP_URL:
        return
    safe_execute(
        "POST",
        WEB_APP_URL,
        payload={"wa_number": wa_number, "action": "pending_reschedule"},
    )


# ── Main Route ─────────────────────────────────────────────
@bp.route("/attendance/process", methods=["POST"])
def process_attendance():
    data = request.get_json(force=True)
    log.info(f"[attendance_router] Incoming payload: {data}")

    wa_number = str(data.get("wa_number", "")).strip()
    client_name = data.get("client_name", "")
    message_text = str(data.get("message", "")).lower().strip()

    if not wa_number or not message_text:
        return jsonify({"ok": False, "error": "Missing wa_number or message"}), 400

    if not any(k in message_text for k in RESCHEDULE_KEYWORDS):
        log.info(f"⚠ No reschedule keyword detected in: {message_text}")
        return jsonify({"ok": True, "ignored": True, "reason": "no match"})

    # Process reschedule
    _update_booking_status(wa_number)
    _log_reschedule(wa_number, client_name)
    _notify_admin(client_name, wa_number)
    _notify_client(wa_number)
    _notify_script(wa_number)

    return jsonify({"ok": True, "action": "pending_reschedule"})
