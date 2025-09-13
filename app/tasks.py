# app/tasks.py
from __future__ import annotations
import logging
from flask import request

from .admin_reminders import run_admin_hourly, run_admin_daily
from .client_reminders import run_client_tomorrow, run_client_next_hour, run_client_weekly

def register_tasks(app):
    @app.post("/tasks/admin-notify")
    def admin_notify():
        """
        Hourly admin summary via CRON.
        - Calls run_admin_hourly() which uses template `admin_hourly_update`.
        """
        try:
            src = request.args.get("src", "unknown")
            logging.info(f"[admin-notify] src={src}")
            run_admin_hourly()
            return "ok", 200
        except Exception:
            logging.exception("admin-notify failed")
            return "error", 500

    @app.post("/tasks/run-reminders")
    def run_reminders():
        """
        Multi-purpose reminder runner.
        Query parameters:
          ?daily=1    → run daily admin recap at 20:00
          ?tomorrow=1 → send client 24h-before reminders
          ?next=1     → send client 1h-before reminders
          ?weekly=1   → send client weekly preview (Sunday 18:00)
        """
        try:
            src = request.args.get("src", "unknown")
            daily = request.args.get("daily", "0") == "1"
            tomorrow = request.args.get("tomorrow", "0") == "1"
            next_hour = request.args.get("next", "0") == "1"
            weekly = request.args.get("weekly", "0") == "1"

            logging.info(
                f"[run-reminders] src={src} daily={daily} tomorrow={tomorrow} next={next_hour} weekly={weekly}"
            )

            if daily:
                run_admin_daily()
                return "ok daily", 200

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
