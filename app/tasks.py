# app/tasks.py
from __future__ import annotations
import logging
from flask import request

from .admin_reminders import run_admin_morning, run_admin_daily
from .client_reminders import run_client_tomorrow, run_client_next_hour, run_client_weekly

from datetime import date
from .utils import _send_to_meta

from . import broadcasts

logger = logging.getLogger(__name__)

def remind_admin_invoices():
    """
    Send Nadine a reminder on the 25th of each month to review invoices.
    """
    today = date.today()
    if today.day != 25:
        return "Not 25th, skipping."

    # Nadine’s WhatsApp number (put in env or config ideally)
    to = "27XXXXXXXXX"  

    message = (
        f"📝 Reminder: Please review PilatesHQ invoices for {today.strftime('%B %Y')}.\n"
        "Use /monthly_report to view and check. Resolve discrepancies before approving."
    )

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message},
    }

    ok, status, body = _send_to_meta(payload)
    if not ok:
        logger.error("[InvoiceReminderError] status=%s body=%s", status, body)
    else:
        logger.info("[InvoiceReminderSent] to=%s status=%s", to, status)

    return body


log = logging.getLogger(__name__)

def register_tasks(app):
    @app.post("/tasks/admin-morning")
    def admin_morning():
        """One-shot admin morning brief (cron 04:00 UTC = 06:00 SAST)."""
        try:
            src = request.args.get("src", "unknown")
            log.info("[admin-morning] src=%s", src)
            sent = run_admin_morning()
            return f"ok morning sent={sent}", 200
        except Exception:
            logging.exception("admin-morning failed")
            return "error", 500

    @app.post("/tasks/admin-notify")
    def admin_notify():
        """Legacy hourly endpoint (kept for backward compatibility)."""
        try:
            src = request.args.get("src", "unknown")
            log.info("[admin-notify] src=%s (legacy; prefer /tasks/admin-morning)", src)
            return "ok", 200
        except Exception:
            logging.exception("admin-notify failed")
            return "error", 500

    @app.post("/tasks/run-reminders")
    def run_reminders():
        """
        Multi-purpose runner:
          ?daily=1     → admin evening recap
          ?tomorrow=1  → client 24h reminders
          ?next=1      → client 1h reminders
          ?weekly=1    → client weekly preview
        """
        try:
            src = request.args.get("src", "unknown")
            daily = request.args.get("daily", "0") == "1"
            tomorrow = request.args.get("tomorrow", "0") == "1"
            next_hour = request.args.get("next", "0") == "1"
            weekly = request.args.get("weekly", "0") == "1"

            logging.info(
                "[run-reminders] src=%s daily=%s tomorrow=%s next=%s weekly=%s",
                src, daily, tomorrow, next_hour, weekly
            )

            if daily:
                sent = run_admin_daily()
                return f"ok daily sent={sent}", 200

            if tomorrow:
                sent = run_client_tomorrow()
                return f"ok tomorrow sent={sent}", 200

            if next_hour:
                sent = run_client_next_hour()
                return f"ok next-hour sent={sent}", 200

            if weekly:
                sent = run_client_weekly()
                return f"ok weekly sent={sent}", 200

            return "no action", 200

        except Exception:
            logging.exception("run-reminders failed")
            return "error", 500

@app.route("/tasks/broadcast", methods=["POST"])
def run_broadcast():
    """
    Example: curl -X POST ".../tasks/broadcast?msg=Spring%20special%20R220" 
    """
    msg = request.args.get("msg", "").strip()
    if not msg:
        return "error: msg required", 400

    # For now, send to ALL clients with WhatsApp
    from .db import db_session
    from .models import Client
    with db_session() as s:
        wa_numbers = [c.wa_number for c in s.query(Client).filter(Client.wa_number.isnot(None)).all()]

    sent = broadcasts.send_broadcast(wa_numbers, msg)
    return f"ok broadcast sent={sent}", 200