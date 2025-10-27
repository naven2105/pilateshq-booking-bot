"""
__init__.py – Phase 17 (Unified Invoices + Payments)
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
 • tasks_router          → Scheduled task endpoints (triggered via GAS)
 • tasks_sheets          → Shared Google Sheets operations
 • client_reminders      → Client messaging & reminders
 • package_events        → Credit & attendance tracking
 • invoices_router       → Unified invoices + payments (Phase 17)
 • schedule_router       → Weekly bookings, reschedule, admin digests
 • dashboard_router      → Weekly/monthly summaries
 • router_diag           → Health & diagnostics

Retired Blueprints:
 • attendance_router     → Replaced by /schedule/mark-reschedule
 • payments_router       → Merged into invoices_router
────────────────────────────────────────────────────────────
"""

import logging
from flask import Flask

# ── Import active blueprints ─────────────────────────────────────────────
from render_backend.app.router_webhook import router_bp
from render_backend.app.tasks_router import tasks_bp
from render_backend.app.tasks_sheets import bp as tasks_sheets_bp
from render_backend.app.client_reminders import bp as client_reminders_bp
from render_backend.app.package_events import bp as package_events_bp
from render_backend.app.invoices_router import bp as invoices_bp             # ✅ Unified Invoices + Payments
from render_backend.app.schedule_router import bp as schedule_bp             # ✅ Bookings + Reschedules
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
    app.register_blueprint(tasks_bp)                                   # /tasks
    app.register_blueprint(tasks_sheets_bp)                            # /tasks/sheets
    app.register_blueprint(client_reminders_bp)                        # /client-reminders
    app.register_blueprint(package_events_bp)                          # /package-events
    app.register_blueprint(invoices_bp, url_prefix="/invoices")        # ✅ Unified router
    app.register_blueprint(schedule_bp, url_prefix="/schedule")
    app.register_blueprint(dashboard_bp, url_prefix="/dashboard")
    app.register_blueprint(diag_bp)

    log.info("✅ All blueprints registered successfully (Unified Invoices + Payments active).")

    # ── Health Check ───────────────────────────────────────────────────
    @app.route("/", methods=["GET"])
    def health():
        """Simple health and route visibility endpoint."""
        return {
            "status": "ok",
            "service": "PilatesHQ Booking Bot",
            "version": "1.7.0",  # ⬆️ Updated for Unified Invoices + Payments
            "routes": list(app.blueprints.keys()),
            "note": (
                "All time-based triggers are handled exclusively by Google Apps Script. "
                "Payments router retired – invoices_router now handles all payment events."
            )
        }, 200

    return app
