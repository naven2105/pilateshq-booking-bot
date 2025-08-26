# app/main.py
import logging
from flask import Flask
from .db import init_db
from .router import register_routes
from .config import LOG_LEVEL

app = Flask(__name__)

# Logging
logging.basicConfig(
    level=getattr(logging, (LOG_LEVEL or "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

# One-time DB init per instance
_inited = False
@app.before_request
def _init_once():
    global _inited
    if not _inited:
        try:
            init_db()
            app.logger.info("✅ DB initialised / verified")
        except Exception:
            app.logger.exception("❌ DB init failed")
        _inited = True

# Health check
@app.get("/")
def health():
    return "OK", 200

# Register webhook routes
register_routes(app)

# Safety net for unhandled errors
@app.errorhandler(Exception)
def _unhandled(e):
    app.logger.exception("[FLASK ERROR] Unhandled")
    return "server_error", 500
