# app/main.py
from flask import Flask
import logging
from app.router import register_routes

# Create Flask app
app = Flask(__name__)

# Setup logging
log_level = "INFO"
logging.basicConfig(level=getattr(logging, log_level))

# Register all routes
register_routes(app)
