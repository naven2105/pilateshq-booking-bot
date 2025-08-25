# main.py
from flask import Flask, request
import logging, os
from db import init_db
from router import route_message

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "your_verify_token_here")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

app = Flask(__name__)
logging.basicConfig(level=getattr(logging, LOG_LEVEL))

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

@app.get("/webhook")
def verify_webhook():
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    return (challenge, 200) if token == VERIFY_TOKEN else ("Verification failed", 403)

@app.post("/webhook")
def webhook():
    data = request.get_json() or {}
    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            for msg in change.get("value", {}).get("messages", []):
                route_message(msg)
    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
