#render_backend/wsgi.py
"""
wsgi.py – PilatesHQ Render Backend Entry Point
────────────────────────────────────────────
This file is used by Gunicorn to launch the Flask app on Render.

Expected project structure:
render_backend/
 ├── wsgi.py
 └── app/
     ├── __init__.py  ← contains create_app()
     ├── router_webhook.py
     ├── invoices_router.py
     ├── client_menu_router.py
     └── ...
────────────────────────────────────────────
"""

import os
from render_backend.app import create_app

# Flask application factory
app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"🚀 Starting PilatesHQ Render Backend on port {port}")
    app.run(host="0.0.0.0", port=port)
