from flask import Flask, request
import logging
from .db import init_db
from .router import register_routes
from .config import VERIFY_TOKEN, LOG_LEVEL

app = Flask(__name__)
logging.basicConfig(level=getattr(logging, LOG_LEVEL.upper()))

_inited = False
@app.before_request
def _init_once():
    global _inited
    if not _inited:
        init_db()
        logging.info("✅ DB initialised / verified")
        _inited = True

@app.get("/")
def health():
    return "OK", 200

# delegate webhook endpoints to router
register_routes(app)
