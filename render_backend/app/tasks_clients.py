# File: render_backend/app/tasks_clients.py
"""
tasks_clients.py
────────────────────────────────────────────
Handles client reminders:
 - Tomorrow’s session reminder
 - Next-hour reminder
Fetches and filters session data from Google Sheets.
"""

import os
import requests
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify
from render_backend.app.utils import send_whatsapp_template

tasks_clients_bp = Blueprint("tasks_clients_bp", __name__)

# ── Config ───────────────────────────────────────────────
SHEET_ID = os.getenv("CLIENT_SHEET_ID", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
TEMPLATE_LANG = os.getenv("TEMPLATE_LANG", "en_US")

TPL_TOMORROW = "client_session_tomorrow_us"
TPL_NEXT_HOUR = "client_session_next_hour_us"

SHEET_URL = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Sessions!A:F?key={GOOGLE_API_KEY}"


# ─────────────────────────────────────────────────────
def fetch_sessions():
    """Fetch all session rows from Google Sheets."""
    try:
        r = requests.get(SHEET_URL, timeout=10)
        r.raise_for_status()
        return r.json().get("values", [])[1:]  # skip header
    except Exception as e:
        print("❌ Failed to fetch sessions from Sheets:", e)
        return []


def parse_sessions(values, target_date, reminder_type):
    """Filter sessions by date, time, and status."""
    sessions = []
    now = datetime.now()

    for row in values:
        try:
            # Expect: [date, name, wa_number, time, status]
            session_date = datetime.strptime(row[0], "%Y-%m-%d").date()
            if str(session_date) != target_date:
                continue

            name = row[1].strip()
            wa_number = row[2].strip()
            time_str = row[3].strip()
            status = row[4].lower().strip() if len(row) > 4 else "confirmed"

            # Skip cancelled / rescheduled
            if status not in ["confirmed", "active"]:
                print(f"🚫 Skipped {name} ({status})")
                continue

            # Skip past sessions (for same-day reminders)
            if reminder_type == "next-hour":
                session_time = datetime.strptime(time_str, "%H:%M").time()
                if datetime.combine(session_date, session_time) < now:
                    print(f"⏩ Skipped past session for {name} at {time_str}")
                    continue

            sessions.append({
                "name": name,
                "wa_number": wa_number,
                "time": time_str,
                "status": status
            })
        except Exception as e:
            print("⚠️ Skipped invalid row:", row, e)

    return sessions


# ─────────────────────────────────────────────────────
@tasks_clients_bp.route("/tasks/client-reminders", methods=["POST"])
def client_reminders():
    """Send reminders to clients for tomorrow or next-hour sessions."""
    data = request.get_json(force=True)
    reminder_type = (data or {}).get("type", "tomorrow").lower()
    print(f"📅 Client reminder trigger received: {reminder_type}")

    values = fetch_sessions()
    if not values:
        return jsonify({"error": "no sessions found"}), 400

    today = datetime.now().date()
    tomorrow = today + timedelta(days=1)

    if reminder_type == "tomorrow":
        target_date = str(tomorrow)
        template_name = TPL_TOMORROW
    else:
        target_date = str(today)
        template_name = TPL_NEXT_HOUR

    sessions = parse_sessions(values, target_date, reminder_type)
    print(f"🧾 Filtered {len(sessions)} sessions for {target_date}")

    sent = []
    for s in sessions:
        result = send_whatsapp_template(
            to=s["wa_number"],
            name=template_name,
            lang=TEMPLATE_LANG,
            variables=[s["time"]]
        )
        sent.append({
            "name": s["name"],
            "ok": result.get("ok"),
            "status": result.get("status_code")
        })

    return jsonify({
        "reminder_type": reminder_type,
        "date": target_date,
        "sent_count": len(sent),
        "sent": sent
    }), 200
