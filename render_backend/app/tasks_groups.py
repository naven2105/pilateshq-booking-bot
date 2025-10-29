"""
tasks_groups.py – Phase 19 (Group Availability Command)
────────────────────────────────────────────────────────────
Handles on-demand queries for session group availability.
Triggered when Nadine types “Groups available” on WhatsApp
or when GAS calls the /tasks/groups endpoint.

Integrates with GAS_GROUPS_URL (Apps Script endpoint)
to fetch current session capacities and attendance counts.
────────────────────────────────────────────────────────────
"""

import os, logging, requests
from flask import Blueprint, request, jsonify

bp = Blueprint("groups_bp", __name__, url_prefix="/tasks")
log = logging.getLogger(__name__)

# ── Environment ─────────────────────────────────────────────
GAS_GROUPS_URL = os.getenv("GAS_GROUPS_URL", "")
ADMIN_WA = os.getenv("ADMIN_NUMBER", "")
TZ = os.getenv("TZ_NAME", "Africa/Johannesburg")


@bp.route("/groups", methods=["POST"])
def groups_available():
    """Handles /tasks/groups POST requests."""
    data = request.get_json(force=True) or {}
    action = data.get("action", "").lower().strip()

    if action != "get_group_availability":
        return jsonify({"ok": False, "error": f"Unsupported action: {action}"})

    if not GAS_GROUPS_URL:
        return jsonify({"ok": False, "error": "Missing GAS_GROUPS_URL env var"})

    try:
        log.info("🔁 Fetching group availability from GAS...")
        res = requests.post(GAS_GROUPS_URL, json={"action": "get_group_availability"}, timeout=15)
        if res.ok:
            result = res.json()
            log.info(f"✅ Group availability fetched successfully → {result}")
            return jsonify({"ok": True, "message": result})
        else:
            log.error(f"❌ GAS returned {res.status_code}: {res.text}")
            return jsonify({"ok": False, "error": res.text})
    except Exception as e:
        log.error(f"❌ groups_available failed → {e}")
        return jsonify({"ok": False, "error": str(e)})
