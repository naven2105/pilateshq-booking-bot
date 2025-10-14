#render_backend/app/__init__.py
# render_backend/app/__init__.py
"""
render_backend/app/__init__.py
────────────────────────────────────────────
Initialises all Flask blueprints for the Render backend.
Automatically registers webhook, tasks, reminder, and package routes.
Now includes:
 - attendance_router  → handles RESCHEDULE requests
"""

import logging
from flask import Flask

# ── Import blueprints ─────────────────────────────
from render_backend.app.router_webhook import router_bp
from render_backend.app.tasks_router import tasks_bp
from render_backend.app.tasks_sheets import bp as tasks_sheets_bp
from render_backend.app.client_reminders import bp as client_reminders_bp
from render_backend.app.package_events import bp as package_events_bp
from render_backend.app.attendance_router import bp as attendance_bp   # ✅ NEW

# ── Setup logging ─────────────────────────────
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def create_app() -> Flask:
    """Initialise and configure the Flask app."""
    app = Flask(__name__)

    # Register all blueprints
    app.register_blueprint(router_bp)
    app.register_blueprint(tasks_bp)
    app.register_blueprint(tasks_sheets_bp)
    app.register_blueprint(client_reminders_bp)
    app.register_blueprint(package_events_bp)
    app.register_blueprint(attendance_bp)   # ✅ NEW: enables /attendance/process route

    log.info("✅ All blueprints registered successfully (including attendance router).")

    # ── Health check ─────────────────────────────
    @app.route("/", methods=["GET"])
    def health():
        return {
            "status": "ok",
            "service": "PilatesHQ Booking Bot",
            "version": "1.1.0"
        }, 200

    return app
