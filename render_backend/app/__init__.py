"""
app/__init__.py
────────────────
Turns `app` into a proper Flask package with an application factory.
"""

import logging
import os
from flask import Flask

# ── Import Blueprints ──
from .router_webhook import router_bp
from .client_reminders import bp as client_reminders_bp  # ⬅️ NEW import

def create_app():
    """Flask application factory."""
    app = Flask(__name__)

    # ── Configure logging ──
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s :: %(message)s"
    )

    # ── Register blueprints ──
    app.register_blueprint(router_bp)
    app.register_blueprint(client_reminders_bp, url_prefix="/tasks")  # ⬅️ NEW route

    return app
