"""
tasks_groups.py – PilatesHQ Phase 19
────────────────────────────────────────────
Responds to admin WhatsApp keyword: "Groups available"
Fetches live session data from Google Apps Script
and returns formatted availability summary.
────────────────────────────────────────────
"""

import os, logging, requests
from flask import Blueprint, request, jsonify

bp = Blueprint("groups_bp", __name__)
log = logging.getLogger(__name__)

# ── Environment Variables ──────────────────────────────────────
GAS_URL = os.getenv("GAS_GROUPS_URL", "")  # new Apps Script endpoint
NADINE_WA = os.getenv("NADINE_WA", "")

# ── Route ──────────────────────────────────────────────────────
@bp.route("/tasks/groups", methods=["POST"])
def groups_available():
    """Proxy GAS request to fetch group openings"""
    try:
        data = request.get_json(force=True)
        if data.get("action") != "get_group_availability":
            return jsonify({"ok": False, "error": "invalid action"})

        if not GAS_URL:
            return jsonify({"ok": False, "error": "missing GAS_GROUPS_URL"})

        log.info("🔁 Fetching group availability from GAS...")
        res = requests.post(GAS_URL, json={"action": "get_group_availability"}, timeout=15)

        if not res.ok:
            log.error(f"❌ GAS request failed → {res.status_code}: {res.text}")
            return jsonify({"ok": False, "error": res.text})

        data = res.json()
        log.info(f"✅ Group availability fetched successfully: {data}")
        return jsonify(data)

    except Exception as e:
        log.error(f"❌ groups_available error: {e}")
        return jsonify({"ok": False, "error": str(e)})
