# app/main.py
from flask import Flask, request
import logging
from .db import init_db
from .router import route_message
from .config import VERIFY_TOKEN, LOG_LEVEL

# Create Flask app
app = Flask(__name__)

# Setup logging
log_level = "INFO"
logging.basicConfig(level=getattr(logging, log_level))

# Register all routes
register_routes(app)
