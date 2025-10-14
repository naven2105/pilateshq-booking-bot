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


# ─────────────────────────────────────────────────────────────
# Stub: Update booking status (Google Sheets version)
# ─────────────────────────────────────────────────────────────
def _update_booking_status(wa_number: str):
    """
    Log the reschedule request for the client (Google Sheets version).
    Since we are not using PostgreSQL, this will be replaced later
    with a Sheets API write or webhook trigger.
    """
    log.info(f"[attendance_router] (Sheets mode) Logging reschedule for {wa_number}")
    # Placeholder: In future, you’ll append this info to a 'Reschedules' sheet
    return True



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

    wa_number = data.get("wa_number")
    client_name = data.get("client_name")
    message = data.get("message", "").lower()

    if "reschedule" in message:
        _update_booking_status(wa_number)

        # ✅ Notify client
        send_whatsapp_template(
            to=wa_number,
            name="client_generic_alert_us",
            lang="en_US",
            variables=[f"Hi {client_name}, we’ve received your reschedule request. Nadine will confirm a new time soon 🤸‍♀️"]
        )

        # ✅ Notify Nadine
        send_whatsapp_template(
            to=os.getenv("NADINE_WA"),
            name="admin_generic_alert_us",
            lang="en_US",
            variables=[f"🔄 {client_name} requested to reschedule their session."]
        )

        return jsonify({"ok": True, "action": "reschedule"})

    return jsonify({"ok": False, "reason": "no reschedule keyword found"}), 400
