"""
wsgi.py
Entry point for Gunicorn (Render deployment)
"""

from flask import Flask
from render_backend.app.router_webhook import router_bp


def create_app():
    app = Flask(__name__)
    app.register_blueprint(router_bp)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
