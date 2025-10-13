#render_backend/wsgi.py
"""
wsgi.py
────────────────────────────────────────────
Main entry point for Gunicorn on Render.
Initialises the Flask app and registers routes.

✅ Updated for Render compatibility:
 • Imports fixed to match current files
 • No references to removed modules
 • Works with tasks_router and tasks_sheets
"""

from flask import Flask, jsonify

# ✅ Correct relative imports
from app.router_webhook import router_bp
from app.tasks_router import tasks_bp
from app.tasks_sheets import bp as tasks_sheets_bp


def create_app():
    """Initialise and configure the Flask app."""
    app = Flask(__name__)

    # Register blueprints
    app.register_blueprint(router_bp)
    app.register_blueprint(tasks_bp)
    app.register_blueprint(tasks_sheets_bp)

    # ── Health check for Render uptime probes ─────────────
    @app.route("/", methods=["GET"])
    def health():
        """Simple health check endpoint."""
        return jsonify({
            "status": "ok",
            "service": "PilatesHQ Booking Bot",
            "version": "1.0.0"
        }), 200

    return app


# ── Gunicorn entrypoint ─────────────────────────────────
app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
