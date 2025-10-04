"""
app/__init__.py
────────────────
Turns `app` into a proper Flask package with an application factory.
"""

import logging
import os
from flask import Flask

# Import the new split router blueprint
from .router_webhook import router_bp


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

    return app
