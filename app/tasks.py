# app/tasks.py
from __future__ import annotations
import logging
from datetime import datetime
from flask import request

from .admin_reminders import run_admin_tick, run_admin_daily
from .client_reminders import run_client_tomorrow, run_client_next_hour, run_client_weekly

log = logging.getLogger(__name__)

# Simple in-memory cron status (per process)
LAST_RUN = {
    "admin_notify": {"ts": None, "result": None},
    "daily": {"ts": None, "result": None},
    "tomorrow": {"ts": None, "result": None},
    "next_hour": {"ts": None, "result": None},
    "weekly": {"ts": None, "result": None},
}

def _mark(job: str, result: str) -> None:
    LAST_RUN[job]["ts"] = datetime.now().isoformat(timespec="seconds")
    LAST_RUN[job]["result"] = result

def register_tasks(app):
    @app.post("/tasks/admin-notify")
    def admin_notify():
        """Hourly admin summary via CRON (template admin_hourly_update)."""
        try:
            src = request.args.get("src", "unknown")
            log.info("[admin-notify] src=%s", src)
            run_admin_tick()
            _mark("admin_notify", "ok")
            return "ok", 200
        except Exception:
            logging.exception("admin-notify failed")
            _mark("admin_notify", "error")
            return "error", 500

    @app.post("/tasks/run-reminders")
    def run_reminders():
        """
        Multi-purpose reminder runner.
          ?daily=1    → admin 20:00 recap
          ?tomorrow=1 → client 24h-before
          ?next=1     → client 1h-before
          ?weekly=1   → client weekly preview (Sun 18:00)
        """
        try:
            src = request.args.get("src", "unknown")
            daily = request.args.get("daily", "0") == "1"
            tomorrow = request.args.get("tomorrow", "0") == "1"
            next_hour = request.args.get("next", "0") == "1"
            weekly = request.args.get("weekly", "0") == "1"

            log.info("[run-reminders] src=%s daily=%s tomorrow=%s next=%s weekly=%s",
                     src, daily, tomorrow, next_hour, weekly)

            if daily:
                run_admin_daily()
                _mark("daily", "ok")
                return "ok daily", 200

            if tomorrow:
                sent = run_client_tomorrow()
                _mark("tomorrow", f"ok sent={sent}")
                return f"ok tomorrow sent={sent}", 200

            if next_hour:
                sent = run_client_next_hour()
                _mark("next_hour", f"ok sent={sent}")
                return f"ok next-hour sent={sent}", 200

            if weekly:
                sent = run_client_weekly()
                _mark("weekly", f"ok sent={sent}")
                return f"ok weekly sent={sent}", 200

            return "no action", 200

        except Exception:
            logging.exception("run-reminders failed")
            _mark("daily", "error")  # generic bucket
            return "error", 500
