# app/main.py
from flask import Flask
from .tasks import register_tasks
from .router import register_routes

app = Flask(__name__)

# Single authoritative health check
@app.get("/health")
def health():
    return "ok", 200

# Register app routes and task endpoints
register_routes(app)
register_tasks(app)

if __name__ == "__main__":
    # Render sets PORT; locally you can run `python -m app.main`
    import os
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
