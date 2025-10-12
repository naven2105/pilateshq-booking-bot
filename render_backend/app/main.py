# app/main.py
"""
Main Flask application for PilatesHQ backend.
Registers all blueprints (webhook, tasks, invoices, etc.)
"""

from flask import Flask, jsonify

# ── Import Blueprints ─────────────────────────────────────────────
from app.router_webhook import router_bp        # WhatsApp inbound webhook
from app.tasks_router import tasks_bp           # Google Apps Script jobs
from app.invoices import bp as invoices_bp      # ✅ /diag/invoice-pdf & /diag/invoice-test

# ── App Factory ──────────────────────────────────────────────────
def create_app():
    app = Flask(__name__)

    # Register all blueprints
    app.register_blueprint(router_bp)                            # /webhook
    app.register_blueprint(tasks_bp, url_prefix="/tasks")         # /tasks/...
    app.register_blueprint(invoices_bp)                           # /diag/...

    # ── Health Check ─────────────────────────────────────────────
    @app.route("/")
    def health():
        return jsonify({
            "status": "ok",
            "service": "PilatesHQ Booking Bot",
            "blueprints": list(app.blueprints.keys())
        })

    return app


# ── Entry point for root/main.py ─────────────────────────────────
app = create_app()
