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
"""

import os
import logging
from flask import Flask

# ─────────────────────────────────────────────────────────────
# Flask App Factory
# ─────────────────────────────────────────────────────────────
def create_app():
    """Create and configure the Flask application."""
    app = Flask(__name__)

    # ── Configure logging ───────────────────────────────
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # ── Register Blueprints ─────────────────────────────
    from .router_webhook import router_bp
    from .invoices_router import bp as invoices_bp
    from .client_behaviour import bp as behaviour_bp
    from .client_menu_router import bp as client_menu_bp

    app.register_blueprint(router_bp, url_prefix="/")
    app.register_blueprint(invoices_bp, url_prefix="/invoices")
    app.register_blueprint(behaviour_bp, url_prefix="/behaviour")
    app.register_blueprint(client_menu_bp, url_prefix="/client-menu")

    # ── Root health check ───────────────────────────────
    @app.route("/health", methods=["GET"])
    def health_root():
        return {"status": "ok", "service": "PilatesHQ Render Backend"}, 200

    return app


# ─────────────────────────────────────────────────────────────
# Gunicorn entrypoint
# ─────────────────────────────────────────────────────────────
app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
