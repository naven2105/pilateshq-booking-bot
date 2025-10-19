"""
render_backend/app/__init__.py
────────────────────────────────────────────
Initialises all Flask blueprints for the Render backend.
Automatically registers webhook, tasks, reminder, package,
attendance, invoice, and dashboard routes.

Blueprints included:
 - router_webhook        → WhatsApp inbound messages
 - tasks_router          → background jobs (daily summaries, etc.)
 - tasks_sheets          → Google Sheets helper endpoints
 - client_reminders      → client WhatsApp reminders
 - package_events        → package or plan tracking (future use)
 - attendance_router     → handles RESCHEDULE requests
 - invoices_router       → handles admin invoice review & sending
 - dashboard_router      → weekly insights + WhatsApp summary (Phase 6)
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
from render_backend.app.dashboard_router import bp as dashboard_bp   # ✅ NEW
from render_backend.app.router_diag import bp as diag_bp

# ── Setup logging ─────────────────────────────
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

def create_app() -> Flask:
    """Initialise and configure the Flask app."""
    app = Flask(__name__)

    # Register all blueprints
    app.register_blueprint(router_bp)                                   # /
    app.register_blueprint(tasks_bp)                                    # /tasks
    app.register_blueprint(tasks_sheets_bp)                             # /tasks-sheets
    app.register_blueprint(client_reminders_bp)                         # /client-reminders
    app.register_blueprint(package_events_bp)                           # /package-events
    app.register_blueprint(attendance_bp)                               # /attendance
    app.register_blueprint(invoices_bp, url_prefix="/invoices")         # /invoices
    app.register_blueprint(dashboard_bp, url_prefix="/dashboard")       # ✅ NEW
    app.register_blueprint(diag_bp)

    log.info("✅ All blueprints registered successfully (including dashboard router).")

    # ── Health check ─────────────────────────────
    @app.route("/", methods=["GET"])
    def health():
        return {
            "status": "ok",
            "service": "PilatesHQ Booking Bot",
            "version": "1.3.0",
            "routes": list(app.blueprints.keys())
        }, 200

    return app
