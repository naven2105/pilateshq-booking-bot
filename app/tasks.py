# app/tasks.py
from __future__ import annotations
import logging
from flask import request

from .admin_reminders import run_admin_morning, run_admin_daily
from .client_reminders import (
    run_client_tomorrow,
    run_client_next_hour,
    run_client_weekly,
)
from .config import ADMIN_NUMBERS, TEMPLATE_LANG
from . import utils

log = logging.getLogger(__name__)


def register_tasks(app):
    # ─────────────────────────────────────────────
    # Admin notifications
    # ─────────────────────────────────────────────

    @app.post("/tasks/admin-morning")
    def admin_morning():
        try:
            src = request.args.get("src", "unknown")
            log.info(f"[admin-morning] src={src} → template=admin_morning_us")
            sent = run_admin_morning()
            return f"ok morning sent={sent}", 200
        except Exception:
            log.exception("admin-morning failed")
            return "error", 500

    @app.post("/tasks/admin-daily")
    def admin_daily():
        try:
            src = request.args.get("src", "unknown")
            log.info(f"[admin-daily] src={src} → template=admin_20h00_us")
            sent = run_admin_daily()
            return f"ok daily sent={sent}", 200
        except Exception:
            log.exception("admin-daily failed")
            return "error", 500

    # ─────────────────────────────────────────────
    # Client reminders
    # ─────────────────────────────────────────────

    @app.post("/tasks/run-reminders")
    def run_reminders():
        """
        Handles client reminders:
          ?tomorrow=1 → send tomorrow reminders (client_session_tomorrow_us)
          ?next=1     → send 1-hour reminders   (client_session_next_hour_us)
          ?weekly=1   → send weekly schedule    (client_weekly_schedule_us)
        """
        try:
            src = request.args.get("src", "unknown")
            daily = request.args.get("daily") == "1"
            tomorrow = request.args.get("tomorrow") == "1"
            next_hour = request.args.get("next") == "1"
            weekly = request.args.get("weekly") == "1"

            log.info(
                f"[run-reminders] src={src} daily={daily} "
                f"tomorrow={tomorrow} next={next_hour} weekly={weekly}"
            )

            sent = 0
            if tomorrow:
                log.info("→ using template=client_session_tomorrow_us")
                sent = run_client_tomorrow()
                return f"ok tomorrow sent={sent}", 200
            elif next_hour:
                log.info("→ using template=client_session_next_hour_us")
                sent = run_client_next_hour()
                return f"ok next-hour sent={sent}", 200
            elif weekly:
                log.info("→ using template=client_weekly_schedule_us")
                sent = run_client_weekly()
                return f"ok weekly sent={sent}", 200
            else:
                return "no reminders triggered", 200

        except Exception:
            log.exception("run-reminders failed")
            return "error", 500

    # ─────────────────────────────────────────────
    # Broadcast (general messages)
    # ─────────────────────────────────────────────

    @app.post("/tasks/broadcast")
    def broadcast():
        """
        Send a general announcement to all admins (for now).
        Uses template: admin_update_us
        Query param:
          ?msg=Spring special – Duo classes at R220!
        """
        try:
            src = request.args.get("src", "unknown")
            msg = request.args.get("msg", "Update from PilatesHQ")

            log.info(f"[broadcast] src={src} msg={msg} → template=admin_update_us")

            sent = 0
            for admin in ADMIN_NUMBERS:
                ok = utils.send_whatsapp_template(
                    admin,
                    "admin_update_us",
                    TEMPLATE_LANG or "en_US",
                    [msg],
                )
                sent += 1 if ok.get("ok") else 0

            return f"ok broadcast sent={sent}", 200
        except Exception:
            log.exception("broadcast failed")
            return "error", 500
