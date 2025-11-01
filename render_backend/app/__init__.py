"""
__init__.py – Phase 24D (Final Unified Integration)
────────────────────────────────────────────────────────────
Initialises all Flask blueprints for the Render backend.

Key Notes:
 • Google Apps Script handles all scheduled triggers 
   (daily, weekly, birthdays, invoices). Render handles 
   only callable HTTP endpoints and real-time WhatsApp events.
 • This backend powers:
     – WhatsApp Webhook Listener
     – Admin Commands & Exports
     – Schedule + Reschedule requests
     – Invoices & Payments
     – Group Availability & Weekly Digests
     – Dashboard summaries
────────────────────────────────────────────────────────────
"""

import logging
from flask import Flask

# ── Import active blueprints ────────────────────────────────────────────
from render_backend.app.router_webhook import router_bp
from render_backend.app.tasks_router import tasks_bp
from render_backend.app.tasks_sheets import bp as tasks_sheets_bp
from render_backend.app.package_events import bp as package_events_bp
from render_backend.app.invoices_router import bp as invoices_bp
from render_backend.app.schedule_router import bp as schedule_bp
from render_backend.app.dashboard_router import bp as dashboard_bp
from render_backend.app.router_diag import bp as diag_bp
from render_backend.app.tasks_groups import bp as groups_bp

# ── Setup logging ───────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s → %(message)s",
)
log = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────────────
# App Factory
# ────────────────────────────────────────────────────────────────────────
def create_app() -> Flask:
    """Initialise and configure the Flask app (Phase 24D)."""
    app = Flask(__name__)

    # ── Register all blueprints ─────────────────────────────────────────
    app.register_blueprint(router_bp)                                   # /webhook
    app.register_blueprint(tasks_bp, url_prefix="/tasks")
    app.register_blueprint(tasks_sheets_bp, url_prefix="/tasks/sheets")
    app.register_blueprint(package_events_bp, url_prefix="/package-events")
    app.register_blueprint(invoices_bp, url_prefix="/invoices")
    app.register_blueprint(schedule_bp, url_prefix="/schedule")          # ✅ fixes 404
    app.register_blueprint(dashboard_bp, url_prefix="/dashboard")
    app.register_blueprint(groups_bp, url_prefix="/tasks/groups")
    app.register_blueprint(diag_bp)

    log.info("✅ All blueprints registered successfully (Phase 24D active).")

    # ── Health Check ───────────────────────────────────────────────────
    @app.route("/", methods=["GET"])
    def health():
        """Simple health and route visibility endpoint."""
        return {
            "status": "ok",
            "service": "PilatesHQ Booking Bot",
            "version": "2.4D",
            "blueprints": sorted(list(app.blueprints.keys())),
            "note": (
                "All automated triggers (reminders, birthdays, invoices) "
                "run via Google Apps Script. "
                "Render handles live WhatsApp commands and admin requests."
            ),
        }, 200

    return app
