"""
admin_actions_router.py
─────────────────────────────────────────────
Phase 10: Admin NLP → Action Bridge
• Parses Nadine's WhatsApp messages like:
    - "Change Mary Smith 5 Oct session to duo"
    - "Take 10% off Mary Smith invoice"
    - "Take R100 off Mary Smith invoice"
• Calls Google Apps Script endpoint to update sessions or apply discounts.
─────────────────────────────────────────────
"""

import os, re, logging, requests
from flask import Blueprint, request, jsonify
from datetime import datetime
from .utils import send_safe_message

bp = Blueprint("admin_actions_bp", __name__)
log = logging.getLogger(__name__)

# Environment variables
NADINE_WA = os.getenv("NADINE_WA", "")
GAS_INVOICE_URL = os.getenv("GAS_INVOICE_URL", "")  # same as attendance.gs endpoint
SHEET_ID = os.getenv("CLIENT_SHEET_ID", "")
TZ = "Africa/Johannesburg"

@bp.route("/admin/action", methods=["POST"])
def admin_action():
    try:
        data = request.get_json(force=True)
        wa_number = data.get("wa_number", "")
        msg = (data.get("message") or "").strip()

        if wa_number != NADINE_WA:
            return jsonify({"ok": False, "error": "Unauthorized sender"})

        # Detect NLP intent
        intent = detect_intent(msg)
        if not intent:
            send_safe_message(NADINE_WA, "⚠️ Sorry, I didn’t understand that command.")
            return jsonify({"ok": False, "message": "Intent not recognized"})

        # Call Google Apps Script
        result = route_to_gas(intent)

        # If a session was changed, trigger invoice refresh confirmation
        if intent["action"] == "update_session_type" and result.get("ok"):
            new_total = result.get("new_total")
            reply = f"✅ {result['message']}"
            if new_total:
                reply += f"\n💰 Current invoice total: R{new_total}"
            send_safe_message(NADINE_WA, reply)
            return jsonify(result)

        # Otherwise, send simple confirmation
        reply = f"✅ {result.get('message')}" if result.get("ok") else f"⚠️ {result.get('error')}"
        send_safe_message(NADINE_WA, reply)
        log.info(f"Nadine action → {msg} → {reply}")
        return jsonify(result)

    except Exception as err:
        log.error(f"admin_action :: {err}")
        send_safe_message(NADINE_WA, f"⚠️ Error: {err}")
        return jsonify({"ok": False, "error": str(err)})


def route_to_gas(intent: dict):
    """Send POST to Google Apps Script WebApp and return its JSON."""
    payload = {**intent, "sheet_id": SHEET_ID}
    try:
        res = requests.post(GAS_INVOICE_URL, json=payload, timeout=20)
        res.raise_for_status()
        data = res.json()
        # Auto-call invoice refresh for update_session_type (safety redundancy)
        if intent["action"] == "update_session_type" and data.get("ok"):
            requests.post(GAS_INVOICE_URL,
                          json={"action": "upsert_from_sessions",
                                "client_name": intent["client_name"],
                                "sheet_id": SHEET_ID},
                          timeout=20)
        return data
    except Exception as e:
        log.error(f"GAS call failed :: {e}")
        return {"ok": False, "error": str(e)}



# ─────────────────────────────────────────────
# Intent Detection
# ─────────────────────────────────────────────
def detect_intent(msg: str):
    """Use simple keyword rules + regex patterns to detect what Nadine wants."""
    m = msg.lower().strip()

    # 1️⃣ Change session type
    # Example: "Change Mary Smith 5 Oct session to duo"
    change_pattern = re.search(r"change\s+([\w\s]+)\s+(\d{1,2}\s+\w+)\s+.*to\s+(\w+)", m)
    if change_pattern:
        name = change_pattern.group(1).title().strip()
        date_raw = change_pattern.group(2)
        new_type = change_pattern.group(3).lower()
        session_date = parse_date_from_text(date_raw)
        return {
            "action": "update_session_type",
            "client_name": name,
            "session_date": session_date,
            "new_type": new_type
        }

    # 2️⃣ Percentage discount
    # Example: "Take 10% off Mary Smith invoice"
    pct_pattern = re.search(r"(\d+)%\s+off\s+([\w\s]+)", m)
    if pct_pattern:
        percent = pct_pattern.group(1)
        name = pct_pattern.group(2).title().strip()
        return {"action": "apply_discount", "client_name": name, "discount": f"{percent}%"}

    # 3️⃣ Absolute discount
    # Example: "Take R100 off Mary Smith invoice"
    abs_pattern = re.search(r"r?\s?(\d+)\s+off\s+([\w\s]+)", m)
    if abs_pattern:
        amount = abs_pattern.group(1)
        name = abs_pattern.group(2).title().strip()
        return {"action": "apply_discount", "client_name": name, "discount": f"R{amount}"}

    return None


# ─────────────────────────────────────────────
# GAS Routing
# ─────────────────────────────────────────────
def route_to_gas(intent: dict):
    """Send POST to Google Apps Script WebApp."""
    payload = {**intent, "sheet_id": SHEET_ID}
    try:
        res = requests.post(GAS_INVOICE_URL, json=payload, timeout=20)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        log.error(f"GAS call failed :: {e}")
        return {"ok": False, "error": str(e)}


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def parse_date_from_text(date_str: str) -> str:
    """
    Convert text like '5 Oct' or '05 October' → ISO 2025-10-05.
    Uses current year.
    """
    try:
        parts = date_str.strip().split()
        day = int(re.sub(r"\D", "", parts[0]))
        month_str = parts[1][:3].title()
        month_map = {
            "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
            "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12
        }
        month = month_map.get(month_str, datetime.now().month)
        year = datetime.now().year
        return f"{year}-{month:02d}-{day:02d}"
    except Exception:
        return datetime.now().strftime("%Y-%m-%d")
