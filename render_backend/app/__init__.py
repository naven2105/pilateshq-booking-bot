"""
__init__.py
────────────────────────────────────────────
Initialises all Flask blueprints for the Render backend.

Now includes:
 • dashboard_router  → Weekly studio insights
 • test_router       → WhatsApp template test endpoint
────────────────────────────────────────────
"""

import logging
from flask import Flask

# ── Import blueprints ─────────────────────────────
from render_backend.app.router_webhook import router_bp  
from render_backend.app.tasks_router import tasks_bp
from render_backend.app.tasks_sheets import bp as tasks_sheets_bp
from render_backend.app.client_reminders import bp as client_reminders_bp
from render_backend.app.package_events import bp as package_events_bp
from render_backend.app.attendance_router import bp as attendance_bp
from render_backend.app.invoices_router import bp as invoices_bp
from render_backend.app.dashboard_router import bp as dashboard_bp
from render_backend.app.router_diag import bp as diag_bp
from render_backend.app.test_router import bp as test_bp   # ✅ NEW – Test Routes

# ── Setup logging ─────────────────────────────
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

def create_app() -> Flask:
    """Initialise and configure the Flask app."""
    app = Flask(__name__)

    # ── Register all blueprints ─────────────────────────────
    app.register_blueprint(router_bp)
    app.register_blueprint(tasks_bp)
    app.register_blueprint(tasks_sheets_bp)
    app.register_blueprint(client_reminders_bp)
    app.register_blueprint(package_events_bp)
    app.register_blueprint(attendance_bp)
    app.register_blueprint(invoices_bp, url_prefix="/invoices")
    app.register_blueprint(dashboard_bp, url_prefix="/dashboard")
    app.register_blueprint(diag_bp)
    app.register_blueprint(test_bp, url_prefix="/test")     # ✅ NEW – Added for test sending

    log.info("✅ All blueprints registered successfully (including dashboard & test routers).")

    # ── Health check ─────────────────────────────
    @app.route("/", methods=["GET"])
    def health():
        return {
            "status": "ok",
            "service": "PilatesHQ Booking Bot",
            "version": "1.4.0",
            "routes": list(app.blueprints.keys())
        }, 200

    return app
