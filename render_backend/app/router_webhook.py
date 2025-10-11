# render_backend/app/router_webhook.py
"""
router_webhook.py
────────────────────────────────────────────
Handles incoming Meta Webhook events (GET verify + POST messages).
Supports:
 - Client messages (reschedule, new leads)
 - Nadine admin commands (pause, resume, report, credits, help)
"""

import os
import requests
from flask import Blueprint, request, jsonify
from render_backend.app.utils import send_whatsapp_template

router_bp = Blueprint("router_bp", __name__)

# ── Environment variables ────────────────────────────────────────────────
VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "")
APPS_SCRIPT_URL = os.getenv("APPS_SCRIPT_URL", "")
NADINE_WA = os.getenv("NADINE_WA", "")  # e.g. 27627597357
TEMPLATE_LANG = os.getenv("TEMPLATE_LANG", "en_US")

# ── Helpers ──────────────────────────────────────────────────────────────
def post_to_apps_script(action: str):
    """Post a simple action to Apps Script (pause/resume/report/credits)."""
    if not APPS_SCRIPT_URL:
        print("⚠️ No Apps Script URL configured.")
        return {"ok": False, "error": "Missing Apps Script URL"}
    try:
        payload = {"action": action}
        r = requests.post(APPS_SCRIPT_URL, json=payload, timeout=10)
        print(f"📤 Sent action={action} → status={r.status_code}")
        return {"ok": r.status_code == 200, "status": r.status_code}
    except Exception as e:
        print(f"❌ Apps Script post failed for action={action}: {e}")
        return {"ok": False, "error": str(e)}


def send_admin_reply(message: str):
    """Send WhatsApp text reply to Nadine."""
    if not NADINE_WA:
        print("⚠️ NADINE_WA not configured.")
        return
    send_whatsapp_template(
        to=NADINE_WA,
        name="admin_generic_alert_us",
        lang=TEMPLATE_LANG,
        variables=[message]
    )

# ───────────────────────────────
# META VERIFICATION HANDSHAKE
# ───────────────────────────────
@router_bp.route("/webhook", methods=["GET"])
def verify():
    """Verify webhook during Meta setup."""
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("✅ Meta webhook verified successfully.")
        return challenge, 200
    print("❌ Meta webhook verification failed.")
    return "Forbidden", 403


# ───────────────────────────────
# META MESSAGE HANDLER
# ───────────────────────────────
@router_bp.route("/webhook", methods=["POST"])
def webhook():
    """Handle incoming messages or status events from Meta."""
    data = request.get_json(force=True)
    print("📩 Webhook received:", data)

    try:
        entry = (data.get("entry") or [{}])[0]
        change = (entry.get("changes") or [{}])[0]
        value = change.get("value", {})

        # ── Case 1: Status updates ───────────────────────
        if "statuses" in value:
            status_info = value["statuses"][0]
            msg_id = status_info.get("id")
            msg_status = status_info.get("status")
            recipient = status_info.get("recipient_id")
            print(f"📬 Status update: {msg_id} → {msg_status} (to {recipient})")
            return jsonify({"status": "status event logged"}), 200

        # ── Case 2: Incoming messages ────────────────────
        if "messages" in value:
            msg = value["messages"][0]
            wa_number = msg.get("from", "")
            msg_text = msg.get("text", {}).get("body", "").strip().lower()
            name = msg.get("profile", {}).get("name", "Unknown")

            print(f"💬 Message from {wa_number}: {msg_text}")

            # ── ADMIN COMMANDS ────────────────────────────
            if wa_number == NADINE_WA:
                if msg_text in ["pause", "resume", "report", "credits", "help"]:
                    print(f"🛠 Admin command from Nadine: {msg_text}")

                    if msg_text == "pause":
                        post_to_apps_script("pause_jobs")
                        send_admin_reply("⏸️ Automation paused.")
                    elif msg_text == "resume":
                        post_to_apps_script("resume_jobs")
                        send_admin_reply("▶️ Automation resumed.")
                    elif msg_text == "report":
                        post_to_apps_script("get_admin_report")
                        send_admin_reply("📊 Studio report is being prepared.")
                    elif msg_text == "credits":
                        post_to_apps_script("get_unused_credits")
                        send_admin_reply("📋 Credits summary requested.")
                    elif msg_text == "help":
                        send_admin_reply(
                            "🧭 Admin Commands:\n"
                            "• report – Studio summary\n"
                            "• credits – Clients with unused credits\n"
                            "• pause – Pause automations\n"
                            "• resume – Resume automations\n"
                            "• help – Show this menu"
                        )
                    return jsonify({"status": "admin command handled"}), 200

            # ── RESCHEDULE (Client Message) ────────────────
            if "reschedule" in msg_text:
                print(f"🔁 Reschedule request from {name} ({wa_number})")
                if APPS_SCRIPT_URL:
                    requests.post(APPS_SCRIPT_URL, json={
                        "wa_number": wa_number,
                        "name": name,
                        "message": msg_text
                    }, timeout=10)
                send_admin_reply(f"Client {name} ({wa_number}) requested to reschedule.")
                return jsonify({"status": "reschedule handled"}), 200

            # ── Default (New Lead / Generic Message) ───────
            send_admin_reply(f"📥 New message from {name} ({wa_number}): {msg_text}")
            return jsonify({"status": "message processed"}), 200

        # ── Unknown event type ───────────────────────────
        print("⚠️ Unknown webhook event:", value)
        return jsonify({"status": "ignored"}), 200

    except Exception as e:
        print("❌ Webhook error:", e)
        return jsonify({"error": str(e)}), 500


# ───────────────────────────────
# HEALTH CHECK ENDPOINT
# ───────────────────────────────
@router_bp.route("/", methods=["GET"])
def health():
    """Simple health check for Render."""
    return jsonify({"status": "ok", "service": "PilatesHQ Booking Bot"}), 200
