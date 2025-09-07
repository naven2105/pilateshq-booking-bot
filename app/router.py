# app/router.py
"""
HTTP routes that are not 'tasks'. Keep /health ONLY in main.py to avoid
endpoint collisions.
"""
import logging
from flask import request, jsonify

# If you need utils/crud here, import them as usual:
# from .utils import normalize_wa, reply_to_whatsapp
# from .crud import ...

def register_routes(app):
    # DO NOT define /health here (it lives in main.py)

    @app.get("/")
    def root():
        return "PilatesHQ bot is running.", 200

    # Example webhook endpoint (keep your existing logic if you already have one)
    @app.post("/webhook")
    def webhook():
        try:
            # Your existing webhook handling goes here.
            # Return 200 quickly so Meta doesn’t retry.
            logging.info("[webhook] inbound")
            return "ok", 200
        except Exception:
            logging.exception("[webhook] error")
            return "error", 200  # still 200 to prevent retries

    # Add any other non-task routes here (but not /health)
    