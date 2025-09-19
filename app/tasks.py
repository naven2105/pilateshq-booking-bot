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

log = logging.getLogger(__name__)


def register_tasks(app):
    # ─────────────────────────────────────────────
    # Admin notifications
    # ─────────────────────────────────────────────

    @app.post("/tasks/admin-morning")
    def admin_morning():
        try:
            src = request.args.get("src", "unknown")
            log.info(f"[admin-morning] src={src}")
            sent = run_admin_morning()
            return f"ok morning sent={sent}", 200
        except Exception:
            log.exception("admin-morning failed")
            return "error", 500

    @app.post("/tasks/admin-daily")
    def admin_daily():
        try:
            src = request.args.get("src", "unknown")
            log.info(f"[admin-daily] src={src}")
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
          ?tomorrow=1 → send tomorrow reminders
          ?next=1     → send 1-hour reminders
          ?weekly=1   → send weekly schedule
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
                sent = run_client_tomorrow()
                return f"ok tomorrow sent={sent}", 200
            elif next_hour:
                sent = run_client_next_hour()
                return f"ok next-hour sent={sent}", 200
            elif weekly:
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
        try:
            src = request.args.get("src", "unknown")
            log.info(f"[broadcast] src={src}")
            # TODO: implement general broadcast logic (marketing / updates)
            return "ok broadcast", 200
        except Exception:
            log.exception("broadcast failed")
            return "error", 500
