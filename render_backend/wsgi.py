"""
wsgi.py
────────────────────────────────────────────
Main entry point for Gunicorn on Render.
Initialises the Flask app and registers routes.
"""

from flask import Flask, jsonify
from render_backend.app.router_webhook import router_bp


def create_app():
    app = Flask(__name__)

    # Register main webhook blueprint
    app.register_blueprint(router_bp)

    # ── Health check for Render uptime probes ────────────────────────────────
    @app.route("/", methods=["GET"])
    def health():
        """Simple health check endpoint."""
        return jsonify({
            "status": "ok",
            "service": "PilatesHQ Booking Bot",
            "version": "1.0.0"
        }), 200

    return app


# Gunicorn entrypoint
app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
