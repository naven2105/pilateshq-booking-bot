from __future__ import annotations
import logging
from flask import Flask
from app.router import register_routes
from app.diag import bp as diag_bp
from app.tasks import register_tasks   # import tasks

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s"
)
logging.getLogger("werkzeug").setLevel(logging.INFO)

app: Flask = Flask(__name__)
register_routes(app)
app.register_blueprint(diag_bp)
register_tasks(app)   # mount /tasks/* endpoints

logging.info("WSGI startup complete; Flask app created.")
