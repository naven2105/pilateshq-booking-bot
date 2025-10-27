"""
__init__.py – Phase 18 (Client Engagement Automation)
────────────────────────────────────────────────────────────
Initialises all Flask blueprints for the Render backend.

Key Notes:
 • All scheduled triggers (morning/evening/weekly summaries)
   are executed by Google Apps Script — not by Render.
 • This backend only exposes callable HTTP endpoints
   for GAS automation and Nadine’s admin commands.
 • No CRON or APScheduler jobs run on Render.

Included Blueprints:
 • router_webhook        → Core WhatsApp event listener
 • tasks_router          → Unified GAS task endpoints (reminders, analytics)
 • tasks_sheets          → Shared Google Sheets operations
 • package_events        → Credit & attendance tracking
 • invoices_router       → Unified invoices + payments
 • schedule_router       → Weekly bookings, reschedule, admin digests
 • dashboard_router      → Weekly/monthly summaries
 • router_diag           → Health & diagnostics

Retired Blueprints:
 • client_reminders      → merged into tasks_router (Phase 18)
 • attendance_router     → replaced by /schedule/mark-reschedule
 • payments_router       → merged into invoices_router
────────────────────────────────────────────────────────────
"""

import logging
from flask import Flask

# ── Import active blueprints ─────────────────────────────────────────────
from render_backend.app.router_webhook import router_bp
from render_backend.app.tasks_router import tasks_bp
from render_backend.app.tasks_sheets import bp as tasks_sheets_bp
from render_backend.app.package_events import bp as package_events_bp
from render_backend.app.invoices_router import bp as invoices_bp           # ✅ Unified Invoices + Payments
from render_backend.app.schedule_router import bp as schedule_bp           # ✅ Bookings + Reschedules
from render_backend.app.dashboard_router import bp as dashboard_bp
from render_backend.app.router_diag import bp as diag_bp

# ── Setup logging ────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
log = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────────────
# App Factory
# ────────────────────────────────────────────────────────────────────────
def create_app() -> Flask:
    """Initialise and configure the Flask app."""
    app = Flask(__name__)

    # ── Register all blueprints ─────────────────────────────────────────
    app.register_blueprint(router_bp)                                  # /webhook
    app.register_blueprint(tasks_bp)                                   # /tasks (now includes client reminders)
    app.register_blueprint(tasks_sheets_bp)                            # /tasks/sheets
    app.register_blueprint(package_events_bp)                          # /package-events
    app.register_blueprint(invoices_bp, url_prefix="/invoices")        # ✅ Unified router
    app.register_blueprint(schedule_bp, url_prefix="/schedule")
    app.register_blueprint(dashboard_bp, url_prefix="/dashboard")
    app.register_blueprint(diag_bp)

    log.info("✅ All blueprints registered successfully (Phase 18 – Client Engagement active).")

    # ── Health Check ───────────────────────────────────────────────────
    @app.route("/", methods=["GET"])
    def health():
        """Simple health and route visibility endpoint."""
        return {
            "status": "ok",
            "service": "PilatesHQ Booking Bot",
            "version": "1.8.0",  # ⬆️ Updated for Phase 18 – Client Engagement Automation
            "routes": list(app.blueprints.keys()),
            "note": (
                "All time-based triggers are handled exclusively by Google Apps Script. "
                "client_reminders merged into tasks_router; payments handled in invoices_router."
            )
        }, 200

    return app
