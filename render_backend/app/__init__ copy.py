
##render_backend/app/__init__.py
"""
__init__.py – PilatesHQ Render Backend (Phase 26)
────────────────────────────────────────────────────────────
Initialises the Flask app and registers all feature blueprints.

✅ Includes:
 • router_webhook      → WhatsApp inbound handler (Meta)
 • invoices_router     → PDF invoice generation & delivery
 • client_behaviour    → Behaviour analytics (from GAS)
 • client_menu_router  → Client Self-Service Menu (NEW)
────────────────────────────────────────────────────────────
Enhancements:
 • Unified structured logging (INFO default)
 • Defensive import handling (graceful skip if module missing)
 • Startup environment diagnostics for Render
 • Clear health endpoint responses
────────────────────────────────────────────────────────────
"""

import os
import logging
from flask import Flask, jsonify

# ─────────────────────────────────────────────────────────────
# Flask App Factory
# ─────────────────────────────────────────────────────────────
def create_app():
    """Create and configure the Flask application."""
    app = Flask(__name__)

    # ── Configure structured logging ───────────────────────────────
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    log = logging.getLogger("pilateshq_init")
    log.info("🚀 Starting PilatesHQ Render Backend")

    # ── Register Blueprints safely ────────────────────────────────
    try:
        from .router_webhook import router_bp
        app.register_blueprint(router_bp, url_prefix="/")
        log.info("✅ router_webhook registered")
    except Exception as e:
        log.error(f"❌ router_webhook failed to register: {e}")

    try:
        from .invoices_router import bp as invoices_bp
        app.register_blueprint(invoices_bp, url_prefix="/invoices")
        log.info("✅ invoices_router registered")
    except Exception as e:
        log.error(f"❌ invoices_router failed to register: {e}")

    try:
        from .client_behaviour import bp as behaviour_bp
        app.register_blueprint(behaviour_bp, url_prefix="/behaviour")
        log.info("✅ client_behaviour registered")
    except Exception as e:
        log.warning(f"⚠️ client_behaviour not loaded: {e}")

    try:
        from .client_menu_router import bp as client_menu_bp
        app.register_blueprint(client_menu_bp, url_prefix="/client-menu")
        log.info("✅ client_menu_router registered")
    except Exception as e:
        log.error(f"❌ client_menu_router failed to register: {e}")

    # ── Root health check ───────────────────────────────
    @app.route("/health", methods=["GET"])
    def health_root():
        """Primary Render health check endpoint."""
        return jsonify({
            "status": "ok",
            "service": "PilatesHQ Render Backend",
            "registered_routes": [
                "/ (Meta Webhook)",
                "/invoices/*",
                "/behaviour/*",
                "/client-menu/*"
            ]
        }), 200

    # ── Environment summary for debug (visible in logs only) ──────
    debug_envs = {
        "WEBHOOK_BASE": os.getenv("WEBHOOK_BASE"),
        "NADINE_WA": os.getenv("NADINE_WA"),
        "TEMPLATE_LANG": os.getenv("TEMPLATE_LANG"),
        "GAS_WEBHOOK_URL": os.getenv("GAS_WEBHOOK_URL"),
    }
    log.info(f"🌍 Environment summary: {debug_envs}")

    return app


# ─────────────────────────────────────────────────────────────
# Gunicorn / Local Entrypoint
# ─────────────────────────────────────────────────────────────
app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    logging.getLogger("pilateshq_init").info(f"🏁 Running Flask app on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
