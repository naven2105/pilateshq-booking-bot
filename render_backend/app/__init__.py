#render_backend/app/__init__.py
"""
app/__init__.py
────────────────
Turns `app` into a proper Flask package with an application factory.
"""

import logging
import os
from flask import Flask
from .client_behaviour import bp as client_behaviour_bp

# ── Import Blueprints ──
from .router_webhook import router_bp
from .client_reminders import bp as client_reminders_bp  

from .package_events import bp as package_events_bp  # blueprint registration

def create_app():
    """Flask application factory."""
    app = Flask(__name__)

    app.register_blueprint(client_behaviour_bp, url_prefix="/tasks")

    # ── Configure logging ──
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s :: %(message)s"
    )

    # ── Register blueprints ──
    app.register_blueprint(router_bp)
    app.register_blueprint(client_reminders_bp, url_prefix="/tasks")  
    app.register_blueprint(package_events_bp, url_prefix="/tasks")

    return app
