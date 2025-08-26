# app/main.py
import logging
import os
from flask import Flask

from .db import init_db
from .router import register_routes

# Create Flask app
app = Flask(__name__)

# Logging setup
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, log_level))
logger = logging.getLogger(__name__)

# One-time DB init
@app.before_request
def _init_once():
    if not getattr(app, "_db_init_done", False):
        try:
            init_db()
            app._db_init_done = True
            logger.info("✅ Database initialized")
        except Exception as e:
            logger.exception("❌ Database init failed: %s", str(e))

# Register all routes (from router.py)
register_routes(app)

# Health check endpoint
@app.route("/", methods=["GET"])
def health():
    return "✅ PilatesHQ Bot is running", 200
