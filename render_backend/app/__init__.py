"""
__init__.py – Phase 19 (Group Availability Command)
────────────────────────────────────────────────────────────
Initialises all Flask blueprints for the Render backend.

Key Notes:
 • Google Apps Script handles all scheduled triggers 
   (daily, weekly, birthday, invoice).  Render executes only 
   callable, on-demand HTTP endpoints.
 • This backend powers:
     – WhatsApp Webhook Listener
     – Task Routers (reminders, birthdays, analytics)
     – Group Availability Queries (Phase 19)
     – Invoices + Payments
     – Schedules + Reschedules + Admin Dashboards
 • No CRON or background threads run on Render.

Active Blueprints:
 • router_webhook    → Core WhatsApp event listener
 • tasks_router      → GAS tasks (reminders, birthdays, analytics)
 • tasks_sheets      → Shared Google Sheets operations
 • package_events    → Credit & attendance tracking
 • invoices_router   → Unified invoices + payments
 • schedule_router   → Weekly bookings, reschedules, admin digests
 • dashboard_router  → Weekly/monthly summaries
 • router_diag       → Health & diagnostics
 • tasks_groups      → 🆕 Phase 19 Group Availability Query

Retired Blueprints:
 • client_reminders  → merged into tasks_router (Phase 18)
 • attendance_router → replaced by /schedule/mark-reschedule
 • payments_router   → merged into invoices_router
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
from render_backend.app.tasks_groups import bp as groups_bp      # 🆕 Phase 19 Group Availability

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
    """Initialise and configure the Flask app (Phase 19)."""
    app = Flask(__name__)

    # ── Register all blueprints ─────────────────────────────────────────
    app.register_blueprint(router_bp)                                   # /webhook
    app.register_blueprint(tasks_bp, url_prefix="/tasks")               # GAS tasks
    app.register_blueprint(tasks_sheets_bp, url_prefix="/tasks/sheets")
    app.register_blueprint(package_events_bp, url_prefix="/package-events")
    app.register_blueprint(invoices_bp, url_prefix="/invoices")
    app.register_blueprint(schedule_bp, url_prefix="/schedule")
    app.register_blueprint(dashboard_bp, url_prefix="/dashboard")
    app.register_blueprint(groups_bp, url_prefix="/tasks/groups")       # 🆕 Phase 19
    app.register_blueprint(diag_bp)

    log.info("✅ All blueprints registered successfully (Phase 19 active).")

    # ── Health Check ───────────────────────────────────────────────────
    @app.route("/", methods=["GET"])
    def health():
        """Simple health and route visibility endpoint."""
        return {
            "status": "ok",
            "service": "PilatesHQ Booking Bot",
            "version": "1.9.0",  # ⬆️ Phase 19 Group Availability update
            "routes": sorted(list(app.blueprints.keys())),
            "note": (
                "All time-based triggers run via Google Apps Script. "
                "client_reminders merged into tasks_router; "
                "payments handled in invoices_router; "
                "group availability via /tasks/groups endpoint."
            ),
        }, 200

    return app
