# app/client_reminders.py
from __future__ import annotations
import logging
from flask import request

# placeholder for SQL and send logic
def run_client_reminders() -> int:
    """
    Placeholder: 
    - D-1 (20:00 previous evening)
    - H-1 (1 hour before session)
    - Post-start ("enjoy your session")
    Returns number of client messages sent.
    """
    logging.info("[CLIENT] reminders tick (not yet implemented)")
    return 0

def register_client_reminders(app):
    @app.post("/tasks/run-reminders")
    def run_reminders():
        try:
            src = request.args.get("src", "unknown")
            daily = request.args.get("daily", "0") == "1"
            logging.info(f"[run-reminders] src={src} daily={daily}")
            if daily:
                # For now, daily=1 is handled by admin_recap instead.
                return "redirected to admin recap", 200
            else:
                sent = run_client_reminders()
                return f"ok clients sent={sent}", 200
        except Exception:
            logging.exception("run-reminders failed")
            return "error", 500
