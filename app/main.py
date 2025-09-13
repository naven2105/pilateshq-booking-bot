# app/main.py
import logging
from flask import Flask
from .db import init_db
from .router import router_bp
from .tasks import register_tasks
from .diag import diag_bp

log = logging.getLogger(__name__)

def create_app():
    app = Flask(__name__)

    # Register blueprints
    app.register_blueprint(router_bp)
    app.register_blueprint(diag_bp)
    register_tasks(app)

    # Initialise DB tables
    with app.app_context():
        try:
            init_db()
            log.info("[DB] Tables created / verified")
        except Exception:
            log.exception("[DB] Failed to initialise")

    return app


app = create_app()
