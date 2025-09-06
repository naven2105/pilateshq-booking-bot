# app/router.py
import logging
from flask import request
from .utils import normalize_wa
from .admin import handle_admin_action
from .crud import client_exists_by_wa
from .prospect import start_or_resume  # to log potential clients

def register_routes(app):
    # idempotent guard
    if getattr(app, "_routes_registered", False):
        logging.debug("[router] routes already registered; skipping")
        return
    app._routes_registered = True

    @app.post("/webhook")
    def webhook():
        try:
            data = request.get_json(silent=True) or {}
            # --- Meta webhook: messages ---
            entries = data.get("entry", [])
            for entry in entries:
                changes = entry.get("changes", [])
                for ch in changes:
                    value = ch.get("value", {})
                    msgs  = value.get("messages", [])
                    for m in msgs:
                        sender = m.get("from") or ""
                        txt = (m.get("text", {}) or {}).get("body") or ""
                        # route to admin flow (you can refine auth in admin.py)
                        handle_admin_action(sender, txt)
            return "ok", 200
        except Exception:
            logging.exception("[ERROR webhook]")
            return "error", 200  # avoid retries from Meta

    # NOTE: do NOT define /health here (only in main.py)
