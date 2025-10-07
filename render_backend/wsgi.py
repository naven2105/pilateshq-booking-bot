# render_backend/wsgi.py
from __future__ import annotations
import logging
from flask import Flask

# Import blueprints
from app.router_webhook import router_bp   # ✅ new split router
from app.diag import diag_bp
from app.tasks import register_tasks

import os
print("📂 Current working directory:", os.getcwd())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s"
)
logging.getLogger("werkzeug").setLevel(logging.INFO)

# ── Create Flask app (single entrypoint for dev + prod) ──
app: Flask = Flask(__name__)

# Register blueprints
app.register_blueprint(router_bp)
app.register_blueprint(diag_bp)

# Register task routes
register_tasks(app)

logging.info("WSGI startup complete; Flask app created.")
