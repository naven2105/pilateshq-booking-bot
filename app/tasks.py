# app/tasks.py
from __future__ import annotations

import logging
from flask import request

from .utils import normalize_wa, send_whatsapp_text  # kept if other modules import
from .config import TZ_NAME, NADINE_WA
from . import crud
from .reminders import run_admin_tick, run_admin_daily, run_client_tick

def register_tasks(app):
    @app.post("/tasks/admin-notify")
    def admin_notify():
        """
        Hourly admin summary via CRON (Render):
          • 06:00 SAST → full day (morning prep)
          • Other hours (within band) → upcoming
          • Always includes “Next hour”
          • Idempotent admin_inbox entry keyed by YYYY-MM-DD-HH|admin-tick
        """
        try:
            src = request.args.get("src", "unknown")
            logging.info(f"[admin-notify] src={src}")
            run_admin_tick()
            return "ok", 200
        except Exception:
            logging.exception("admin-notify failed")
            return "error", 500

    @app.post("/tasks/run-reminders")
    def run_reminders():
        """
        - daily=0 (default): send client reminders (D-1 & H-1).
        - daily=1: 20:00 SAST admin recap (today) + tomorrow preview, with inbox entry.
        """
        try:
            src = request.args.get("src", "unknown")
            daily = request.args.get("daily", "0") == "1"
            logging.info(f"[run-reminders] src={src} daily={daily}")

            if daily:
                run_admin_daily()
                return "ok sent=0", 200

            sent = run_client_tick()
            return f"ok sent={sent}", 200

        except Exception:
            logging.exception("run-reminders failed")
            return "error", 500
