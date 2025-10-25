"""
__init__.py
────────────────────────────────────────────
Initialises all Flask blueprints for the Render backend.

Now includes:
 • dashboard_router   → Weekly studio insights
 • payments_router    → Payment recording & auto-match (Phase 14)
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
from render_backend.app.payments_router import bp as payments_bp      # ✅ NEW – Payments Router
from render_backend.app.router_diag import bp as diag_bp

# ── Setup logging ─────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# App Factory
# ─────────────────────────────────────────────────────────────
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
    app.register_blueprint(payments_bp, url_prefix="/payments")       # ✅ Phase 14 – Auto-Match Payments
    app.register_blueprint(diag_bp)
    #app.register_blueprint(test_bp, url_prefix="/test")               # Optional test router

    log.info("✅ All blueprints registered successfully (includes dashboard & payments routers).")

    # ── Health check ─────────────────────────────
    @app.route("/", methods=["GET"])
    def health():
        """Simple health and route visibility endpoint."""
        return {
            "status": "ok",
            "service": "PilatesHQ Booking Bot",
            "version": "1.5.0",  # ⬆️ incremented for Phase 14
            "routes": list(app.blueprints.keys())
        }, 200

    return app
