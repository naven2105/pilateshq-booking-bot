# app/tasks.py
from __future__ import annotations
import logging
from flask import request

from .admin_reminders import run_admin_tick, run_admin_daily
from .client_reminders import run_client_tomorrow, run_client_next_hour, run_client_weekly
from . import utils

log = logging.getLogger(__name__)

def register_tasks(app):
    @app.post("/tasks/admin-notify")
    def admin_notify():
        """
        Hourly admin summary via CRON.
        - Calls run_admin_tick() which uses template `admin_hourly_update`.
        """
        try:
            src = request.args.get("src", "unknown")
            log.info("[admin-notify] src=%s", src)
            run_admin_tick()
            utils.stamp("admin-notify")
            return "ok", 200
        except Exception:
            logging.exception("admin-notify failed")
            utils.incr_error("cron_admin_notify")
            return "error", 500

    @app.post("/tasks/run-reminders")
    def run_reminders():
        """
        Multi-purpose reminder runner.
        Query parameters:
          ?daily=1     → run daily admin recap at 20:00
          ?tomorrow=1  → send client 24h-before reminders
          ?next=1      → send client 1h-before reminders
          ?weekly=1    → send client weekly preview (Sunday 18:00)
        """
        try:
            src = request.args.get("src", "unknown")
            daily = request.args.get("daily", "0") in ("1", "true", "True")
            tomorrow = request.args.get("tomorrow", "0") in ("1", "true", "True")
            next_hour = request.args.get("next", "0") in ("1", "true", "True")
            weekly = request.args.get("weekly", "0") in ("1", "true", "True")

            log.info("[run-reminders] src=%s daily=%s tomorrow=%s next=%s weekly=%s",
                     src, daily, tomorrow, next_hour, weekly)

            if daily:
                run_admin_daily()
                utils.stamp("admin-daily")
                return "ok daily", 200

            if tomorrow:
                sent = run_client_tomorrow()
                utils.stamp("client-tomorrow")
                return f"ok tomorrow sent={sent}", 200

            if next_hour:
                sent = run_client_next_hour()
                utils.stamp("client-next-hour")
                return f"ok next-hour sent={sent}", 200

            if weekly:
                sent = run_client_weekly()
                utils.stamp("client-weekly")
                return f"ok weekly sent={sent}", 200

            # No flags: record the hit so cron-status still shows activity
            utils.stamp("run-reminders")
            return "no action", 200

        except Exception:
            logging.exception("run-reminders failed")
            utils.incr_error("cron_run_reminders")
            return "error", 500
