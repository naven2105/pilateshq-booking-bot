from __future__ import annotations
import json
import logging
import os
from urllib.parse import urlparse

import requests
from flask import Blueprint, request, jsonify, current_app

from .utils import send_whatsapp_text
from .utils import GRAPH_URL, ACCESS_TOKEN  # imported only to display host and to use for test send

bp = Blueprint("diag", __name__, url_prefix="/diag")

@bp.get("/ping")
def ping():
    """Simple app health with safe env hints (no secrets)."""
    graph_host = ""
    try:
        graph_host = urlparse(GRAPH_URL).netloc
    except Exception:
        graph_host = "(invalid GRAPH_URL)"
    return jsonify({
        "ok": True,
        "service": "pilateshq-bot",
        "graph_host": graph_host,
        "has_access_token": bool(ACCESS_TOKEN),
    }), 200

@bp.get("/webhook-selftest")
def webhook_selftest():
    """
    Calls our own /webhook with a minimal WhatsApp-like payload to prove the route +
    public handler path work. Does NOT require Meta.
    """
    try:
        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "id": "wamid.SELFTEST",
                            "from": "27835534607",
                            "type": "text",
                            "text": {"body": "hi (selftest)"},
                        }]
                    }
                }]
            }]
        }
        # Post to our own app
        url = request.url_root.rstrip("/") + "/webhook"
        r = requests.post(url, json=payload, timeout=10)
        return jsonify({"posted_to": url, "status": r.status_code, "body": r.text}), 200
    except Exception as e:
        logging.exception("webhook selftest failed")
        return jsonify({"ok": False, "error": str(e)}), 500

@bp.post("/wa-test")
def wa_test():
    """
    Sends a plain text via WhatsApp Cloud API using current GRAPH_URL/ACCESS_TOKEN.
    Usage: POST /diag/wa-test?to=27835534607  (no JSON body needed)
    """
    to = (request.args.get("to") or "").strip()
    if not to:
        return jsonify({"ok": False, "error": "missing ?to=278... parameter"}), 400
    try:
        res = send_whatsapp_text(to, "PilatesHQ Cloud API test ✅")
        code = res.get("status_code", 200)
        return jsonify({"ok": code < 400, "response": res}), (200 if code < 400 else 500)
    except Exception as e:
        logging.exception("wa-test send failed")
        return jsonify({"ok": False, "error": str(e)}), 500
