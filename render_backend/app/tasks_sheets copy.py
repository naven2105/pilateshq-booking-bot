#app/tasks_sheets.py
"""
tasks_sheets.py
────────────────────────────────────────────
Bridge between Render (Python backend) and Google Sheets Apps Script.
Handles:
 - add_session
 - add_client
 - get_clients (new)
"""

import logging
import os
import requests
from flask import Blueprint, request, jsonify

bp = Blueprint("tasks_sheets", __name__)
log = logging.getLogger(__name__)

WEB_APP_URL = os.getenv("WEB_APP_URL")  # Google Apps Script web app endpoint


@bp.route("/tasks/sheets", methods=["POST"])
def handle_sheets():
    """
    Receive a payload and forward to Google Apps Script.
    Supports:
     - add_session
     - add_client
     - get_clients
    """
    try:
        body = request.get_json(force=True)
        action = (body or {}).get("action")

        if not WEB_APP_URL:
            raise ValueError("WEB_APP_URL not configured in environment")

        # ── 1️⃣ Fetch Clients Data ───────────────────────────────
        if action == "get_clients":
            export_url = f"{WEB_APP_URL}?action=export_clients"
            log.info(f"[Sheets] Fetching clients from {export_url}")
            res = requests.get(export_url, timeout=10)
            res.raise_for_status()
            data = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}
            return jsonify({"ok": True, "clients": data.get("clients", data)})

        # ── 2️⃣ Add Session / Client ─────────────────────────────
        if action in {"add_session", "add_client"}:
            log.info(f"[Sheets] Forwarding {action} → Apps Script")
            res = requests.post(WEB_APP_URL, json=body, timeout=10)
            res.raise_for_status()
            data = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}
            return jsonify({"ok": True, "result": data})

        # ── 3️⃣ Default / Unsupported ─────────────────────────────
        log.warning(f"[Sheets] Unsupported action: {action}")
        return jsonify({"ok": False, "error": f"Unsupported action: {action}"}), 400

    except Exception as e:
        log.exception("❌ Error in /tasks/sheets")
        return jsonify({"ok": False, "error": str(e)}), 500
