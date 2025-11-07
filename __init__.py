##render_backend/__init__.py
"""
__init__.py – PilatesHQ Render Backend (Phase 30S)
────────────────────────────────────────────────────────────
Initialises the Flask app and registers all feature blueprints.

Includes:
 • router_webhook       → WhatsApp inbound handler (Meta)
 • invoices_router      → PDF invoice generation & delivery
 • client_behaviour     → Behaviour analytics (from GAS)
 • client_menu_router   → Client Self-Service Menu
 • tasks_router         → Time-based jobs bridge (GAS → WhatsApp)
 • admin_exports_router → Admin exports (standardised “(x)” markers)
────────────────────────────────────────────────────────────
"""

import os
import logging
from flask import Flask, jsonify

def create_app():
    app = Flask(__name__)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    log = logging.getLogger("pilateshq_init")
    log.info("🚀 Starting PilatesHQ Render Backend")

    # router_webhook
    try:
        from .router_webhook import router_bp
        app.register_blueprint(router_bp, url_prefix="/")
        log.info("✅ router_webhook registered")
    except Exception as e:
        log.error(f"❌ router_webhook failed to register: {e}")

    # invoices_router
    try:
        from .invoices_router import bp as invoices_bp
        app.register_blueprint(invoices_bp, url_prefix="/invoices")
        log.info("✅ invoices_router registered")
    except Exception as e:
        log.error(f"❌ invoices_router failed to register: {e}")

    # client_behaviour
    try:
        from .client_behaviour import bp as behaviour_bp
        app.register_blueprint(behaviour_bp, url_prefix="/behaviour")
        log.info("✅ client_behaviour registered")
    except Exception as e:
        log.warning(f"⚠️ client_behaviour not loaded: {e}")

    # client_menu_router
    try:
        from .client_menu_router import bp as client_menu_bp
        app.register_blueprint(client_menu_bp, url_prefix="/client-menu")
        log.info("✅ client_menu_router registered")
    except Exception as e:
        log.error(f"❌ client_menu_router failed to register: {e}")

    # tasks_router (GAS → reminders bridge)
    try:
        from .tasks_router import tasks_bp
        app.register_blueprint(tasks_bp, url_prefix="/tasks")
        log.info("✅ tasks_router registered")
    except Exception as e:
        log.error(f"❌ tasks_router failed to register: {e}")

    # admin_exports_router (standardised “(x)”)
    try:
        from .admin_exports_router import bp as admin_exports_bp
        app.register_blueprint(admin_exports_bp, url_prefix="/admin")
        log.info("✅ admin_exports_router registered")
    except Exception as e:
        log.error(f"❌ admin_exports_router failed to register: {e}")

    @app.route("/health", methods=["GET"])
    def health_root():
        return jsonify({
            "status": "ok",
            "service": "PilatesHQ Render Backend",
            "registered_routes": [
                "/ (Meta Webhook)",
                "/invoices/*",
                "/behaviour/*",
                "/client-menu/*",
                "/tasks/*",
                "/admin/*"
            ]
        }), 200

    debug_envs = {
        "WEBHOOK_BASE": os.getenv("WEBHOOK_BASE"),
        "NADINE_WA": os.getenv("NADINE_WA"),
        "TEMPLATE_LANG": os.getenv("TEMPLATE_LANG"),
        "GAS_WEBHOOK_URL": os.getenv("GAS_WEBHOOK_URL"),
    }
    log.info(f"🌍 Environment summary: {debug_envs}")
    return app

app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    logging.getLogger("pilateshq_init").info(f"🏁 Running Flask app on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
