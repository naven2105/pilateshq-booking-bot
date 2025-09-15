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
    @app.post("/tasks/admin-morning")
    def admin_morning():
        """
        One-shot admin morning brief (06:00 SAST via cron @ 04:00 UTC).
        Uses the approved 'admin_20h00' template with:
          {{1}} = count of time slots booked today
          {{2}} = single-line 'HH:MM(count): names • HH:MM(count): names ...'
        """
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
        """
        Legacy hourly endpoint. Keep for backward compatibility.
        Recommendation: disable the hourly Render job and use /tasks/admin-morning instead.
        """
        try:
            src = request.args.get("src", "unknown")
            log.info("[admin-notify] src=%s (legacy; prefer /tasks/admin-morning)", src)
            # No-op or you could call run_admin_morning() if you want to reuse it
            return "ok", 200
        except Exception:
            logging.exception("admin-notify failed")
            return "error", 500

    @app.post("/tasks/run-reminders")
    def run_reminders():
        """
        Multi-purpose reminder runner.
        Query parameters:
          ?daily=1     → run admin evening recap (20:00 SAST / 18:00 UTC) using admin_20h00
          ?tomorrow=1  → client 24h-before reminders
          ?next=1      → client 1h-before reminders
          ?weekly=1    → client weekly preview (Sunday 18:00 SAST / 16:00 UTC)
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
