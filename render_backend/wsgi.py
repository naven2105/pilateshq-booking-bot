#render_backend/wsgi.py
"""
wsgi.py
────────────────────────────────────────────
Main entry point for Gunicorn on Render.
Loads Flask app via create_app() from render_backend.app.

✅ Simplified structure:
 - Single import from render_backend.app
 - All routes registered automatically in app/__init__.py
 - Clean and Render-ready for deployment
"""

from render_backend.app import create_app

# ── Gunicorn entrypoint ─────────────────────────────
app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
