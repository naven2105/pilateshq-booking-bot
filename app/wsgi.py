# app/wsgi.py
from __future__ import annotations
import logging
from flask import Flask
from app.router import register_routes

# Configure logging (so Render logs are readable)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s"
)
logging.getLogger("werkzeug").setLevel(logging.INFO)

# Create app and register routes
app: Flask = Flask(__name__)
register_routes(app)

# Probe log so we know startup succeeded
logging.info("WSGI startup complete; Flask app created.")
