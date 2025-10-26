"""
__init__.py – Phase 16 (Schedule + Reminders Integration)
────────────────────────────────────────────────────────────
Initialises all Flask blueprints for the Render backend.

Notes:
 • All time-based triggers (06h00 morning briefs, 20h00 previews)
   are executed by Google Apps Script, not by Render.
 • Render backend only exposes callable HTTP endpoints
   used by GAS or Nadine’s admin commands.
 • No CRON or APScheduler jobs run in Render.

Included Blueprints:
 • router_webhook        → Core WhatsApp event listener
 • tasks_router          → Scheduled task endpoints (triggered via GAS)
 • tasks_sheets          → Shared Google Sheets operations
 • client_reminders      → Client messaging & reminders
 • package_events        → Credit & attendance tracking
 • attendance_router     → Session reschedules & no-shows
 • invoices_router       → PDF generation & invoice delivery
 • payments_router       → Payment recording & auto-match
 • schedule_router       → Weekly bookings, reschedule, admin digests (Phase 16)
 • dashboard_router      → Weekly studio insights (manual)
 • router_diag           → Health & diagnostics
────────────────────────────────────────────────────────────
"""

import logging
from flask import Flask

# ── Import blueprints ─────────────────────────────────────────────
from render_backend.app.router_webhook import router_bp
from render_backend.app.tasks_router import tasks_bp
from render_backend.app.tasks_sheets import bp as tasks_sheets_bp
from render_backend.app.client_reminders import bp as client_reminders_bp
from render_backend.app.package_events import bp as package_events_bp
from render_backend.app.attendance_router import bp as attendance_bp
from render_backend.app.invoices_router import bp as invoices_bp
from render_backend.app.payments_router import bp as payments_bp
from render_backend.app.schedule_router import bp as schedule_bp      # ✅ Phase 16 – New Schedule + Reminders
from render_backend.app.dashboard_router import bp as dashboard_bp
from render_backend.app.router_diag import bp as diag_bp

# ── Setup logging ──────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────
# App Factory
# ──────────────────────────────────────────────────────────────────
def create_app() -> Flask:
    """Initialise and configure the Flask app."""
    app = Flask(__name__)

    # ── Register all blueprints ───────────────────────────────────
    app.register_blueprint(router_bp)                                  # /webhook
    app.register_blueprint(tasks_bp)                                   # /tasks
    app.register_blueprint(tasks_sheets_bp)                            # /tasks/sheets
    app.register_blueprint(client_reminders_bp)                        # /client-reminders
    app.register_blueprint(package_events_bp)                          # /package-events
    app.register_blueprint(attendance_bp)                              # /attendance
    app.register_blueprint(invoices_bp, url_prefix="/invoices")
    app.register_blueprint(payments_bp, url_prefix="/payments")
    app.register_blueprint(schedule_bp, url_prefix="/schedule")        # ✅ Phase 16 addition
    app.register_blueprint(dashboard_bp, url_prefix="/dashboard")
    app.register_blueprint(diag_bp)

    log.info("✅ All blueprints registered successfully (includes schedule, dashboard, and payments routers).")

    # ── Health check ──────────────────────────────────────────────
    @app.route("/", methods=["GET"])
    def health():
        """Simple health and route visibility endpoint."""
        return {
            "status": "ok",
            "service": "PilatesHQ Booking Bot",
            "version": "1.6.0",  # ⬆️ Updated for Schedule + Reminders Integration
            "routes": list(app.blueprints.keys()),
            "note": "All time-based triggers handled exclusively by Google Apps Script."
        }, 200

    return app
