# app/wsgi.py
from __future__ import annotations
import logging
from flask import Flask
from app.router import router_bp
from app.diag import diag_bp
from app.tasks import register_tasks
from app.db import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s"
)
logging.getLogger("werkzeug").setLevel(logging.INFO)

# Create Flask app (single entrypoint for dev + prod)
app: Flask = Flask(__name__)

# Register blueprints
app.register_blueprint(router_bp)
app.register_blueprint(diag_bp)

# Register task routes
register_tasks(app)

# Initialise DB tables at startup
with app.app_context():
    try:
        init_db()
        logging.info("[DB] Tables created / verified")
    except Exception:
        logging.exception("[DB] Failed to initialise")

logging.info("WSGI startup complete; Flask app created.")
