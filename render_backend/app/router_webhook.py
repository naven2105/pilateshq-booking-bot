"""
router_webhook.py – Phase 27J (Enhanced Debug Logs + Client Lookup Trace)
────────────────────────────────────────────────────────────
Handles all incoming Meta Webhook events (GET verify + POST messages).

✅ Improvements vs 27I:
 • Adds detailed debug logs for client lookup (GAS response printed)
 • Logs full message path: admin / NLP / client / guest
 • Confirms client fallback route execution
────────────────────────────────────────────────────────────
"""

import os
import json
import re
import requests
from flask import Blueprint, request, jsonify
from .utils import send_whatsapp_text, send_whatsapp_template, normalize_wa
from .client_reschedule_handler import handle_reschedule_event
from .client_menu_router import send_client_menu

# ─────────────────────────────────────────────────────────────
router_bp = Blueprint("router_bp", __name__)

# ── Environment variables ─────────────────────────────────────
VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "")
WEBHOOK_BASE = os.getenv("WEBHOOK_BASE", "https://pilateshq-booking-bot.onrender.com")
NADINE_WA = os.getenv("NADINE_WA", "")
TEMPLATE_LANG = os.getenv("TEMPLATE_LANG", "en_US")
TEMPLATE_GUEST_WELCOME = os.getenv("TEMPLATE_GUEST_WELCOME", "guest_welcome_us")
GAS_WEBHOOK_URL = os.getenv("GAS_WEBHOOK_URL", "")
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"

# ── Endpoint constants ────────────────────────────────────────
STANDING_ENDPOINT = f"{WEBHOOK_BASE}/tasks/standing/command"
INVOICE_ENDPOINT = f"{WEBHOOK_BASE}/invoices/review-one"
UNPAID_ENDPOINT = f"{WEBHOOK_BASE}/invoices/unpaid"
CLIENT_MENU_ACTION_ENDPOINT = f"{WEBHOOK_BASE}/client-menu/action"

# ── Global timeout constant ───────────────────────────────────
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "35"))  # seconds

# ── Keyword sets for NLP routing ──────────────────────────────
SCHEDULE_KWS = {
    "schedule", "schedules", "my schedule", "upcoming", "next week", "this week",
    "booking", "bookings", "class", "classes", "session", "sessions", "timetable",
}
INVOICE_KWS = {
    "invoice", "invoices", "latest invoice", "my invoice", "bill", "billing",
    "statement", "account", "amount due", "balance",
}


# ─────────────────────────────────────────────────────────────
# Helper: Admin template notification
# ─────────────────────────────────────────────────────────────
def notify_admin(message: str):
    try:
        send_whatsapp_template(
            NADINE_WA, "admin_generic_alert_us", TEMPLATE_LANG, [message],
        )
        print(f"✅ Admin alert: {message}")
    except Exception as e:
        print(f"⚠️ notify_admin failed: {e}")


# ─────────────────────────────────────────────────────────────
# Helpers: message extraction & NLP keyword matching
# ─────────────────────────────────────────────────────────────
def extract_message_text(msg: dict) -> str:
    """Normalizes WhatsApp message content to a command-ish string."""
    mtype = (msg.get("type") or "").lower()

    if mtype == "text":
        body = (msg.get("text") or {}).get("body", "")
        return body.strip().upper()

    if mtype == "interactive":
        i = msg.get("interactive") or {}
        if i.get("button_reply"):
            b = i["button_reply"]
            return (b.get("id") or b.get("title") or "").strip().upper()
        if i.get("list_reply"):
            l = i["list_reply"]
            return (l.get("id") or l.get("title") or "").strip().upper()

    if mtype == "button":
        b = msg.get("button") or {}
        return (b.get("payload") or b.get("text") or "").strip().upper()

    return ""


def _normalize_for_nlp(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _matches_any(text: str, keywords: set[str]) -> bool:
    return any(kw in text for kw in keywords)


def forward_client_action(payload: str, wa_number: str, name: str):
    """Forward an NLP-matched or button action to client_menu_router."""
    try:
        requests.post(
            CLIENT_MENU_ACTION_ENDPOINT,
            json={"wa_number": wa_number, "name": name, "payload": payload},
            timeout=REQUEST_TIMEOUT,
        )
        print(f"➡️ Forwarded action '{payload}' to client_menu_router for {wa_number}")
    except Exception as e:
        print(f"⚠️ Failed to forward client action '{payload}': {e}")


# ─────────────────────────────────────────────────────────────
# META VERIFICATION HANDSHAKE
# ─────────────────────────────────────────────────────────────
@router_bp.route("/webhook", methods=["GET"])
def verify():
    if (
        request.args.get("hub.mode") == "subscribe"
        and request.args.get("hub.verify_token") == VERIFY_TOKEN
    ):
        print("✅ Meta webhook verified.")
        return request.args.get("hub.challenge"), 200
    return "Forbidden", 403


# ─────────────────────────────────────────────────────────────
# META MESSAGE HANDLER
# ─────────────────────────────────────────────────────────────
@router_bp.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    if DEBUG_MODE:
        try:
            print("📩 Full webhook (DEBUG):", json.dumps(data, indent=2))
        except Exception:
            print("📩 Full webhook (DEBUG): <non-serializable payload>")

    try:
        entry = (data.get("entry") or [{}])[0]
        change = (entry.get("changes") or [{}])[0]
        value = change.get("value", {})

        if "statuses" in value:
            return jsonify({"ok": True, "type": "status"}), 200
        if "messages" not in value:
            return jsonify({"ok": True, "type": "ignored"}), 200

        msg = value["messages"][0]
        wa_number = normalize_wa(msg.get("from", ""))
        contacts = value.get("contacts", [])
        profile_name = contacts[0]["profile"]["name"] if contacts else "Unknown"
        cmd_upper = extract_message_text(msg)
        lower_text = cmd_upper.lower()

        print(f"💬 Received message '{cmd_upper}' from {profile_name} ({wa_number})")

        # ─────────────────────────────
        # ADMIN COMMANDS
        # ─────────────────────────────
        if wa_number == NADINE_WA:
            print("👑 Admin message detected.")
            if any(lower_text.startswith(c) for c in ["book ", "suspend ", "resume "]):
                r = requests.post(
                    STANDING_ENDPOINT,
                    json={"from": wa_number, "text": cmd_upper},
                    timeout=REQUEST_TIMEOUT,
                )
                notify_admin(f"Standing command processed ({r.status_code})")
                return jsonify({"status": "standing handled"}), 200

            if lower_text.startswith("invoice "):
                client = cmd_upper.split(" ", 1)[1].strip()
                requests.post(
                    INVOICE_ENDPOINT, json={"client_name": client}, timeout=REQUEST_TIMEOUT
                )
                notify_admin(f"Invoice sent for {client}")
                return jsonify({"status": "invoice handled"}), 200

            send_whatsapp_template(
                wa_number, "admin_generic_alert_us", TEMPLATE_LANG, [f"You sent '{cmd_upper}'."]
            )
            return jsonify({"status": "admin fallback"}), 200

        # ─────────────────────────────
        # CLIENT MENU / ACTIONS
        # ─────────────────────────────
        if lower_text in ["menu", "help", "hi", "hello", "start"]:
            print("📋 Client requested menu (keyword trigger).")
            send_client_menu(wa_number, profile_name)
            return jsonify({"status": "menu sent"}), 200

        # Buttons or direct payloads
        if cmd_upper in ("MY_SCHEDULE", "MY SCHEDULE"):
            forward_client_action("MY_SCHEDULE", wa_number, profile_name)
            return jsonify({"status": "client action forwarded"}), 200
        if cmd_upper in ("VIEW_INVOICE", "VIEW LATEST INVOICE"):
            forward_client_action("VIEW_INVOICE", wa_number, profile_name)
            return jsonify({"status": "client action forwarded"}), 200

        # NLP text routing
        norm = _normalize_for_nlp(lower_text)
        if _matches_any(norm, SCHEDULE_KWS):
            print("🧭 NLP match → MY_SCHEDULE")
            forward_client_action("MY_SCHEDULE", wa_number, profile_name)
            return jsonify({"status": "client action forwarded"}), 200
        if _matches_any(norm, INVOICE_KWS):
            print("🧭 NLP match → VIEW_INVOICE")
            forward_client_action("VIEW_INVOICE", wa_number, profile_name)
            return jsonify({"status": "client action forwarded"}), 200

        # Reschedule / cancel
        if any(x in norm for x in ["reschedule", "cancel", "cant make", "can't make", "no show", "skip"]):
            print("🔁 Detected reschedule or cancellation phrase.")
            return handle_reschedule_event(profile_name, wa_number, cmd_upper, is_admin=False)

        # ─────────────────────────────
        # CLIENT LOOKUP → fallback menu if known
        # ─────────────────────────────
        print(f"🔍 Performing client lookup for WA={wa_number}")
        lookup = {}
        if GAS_WEBHOOK_URL:
            try:
                r = requests.post(
                    GAS_WEBHOOK_URL,
                    json={"action": "lookup_client_name", "wa_number": wa_number},
                    timeout=REQUEST_TIMEOUT,
                )
                print(f"🔎 GAS responded ({r.status_code}): {r.text[:300]}")
                lookup = r.json() if r.ok else {}
            except Exception as e:
                print(f"⚠️ lookup_client_name request failed: {e}")

        if lookup.get("ok"):
            client_found = lookup.get("client_name") or profile_name
            print(f"✅ Known client detected ({client_found}) → Sending client menu.")
            send_client_menu(wa_number, client_found)
            return jsonify({"status": "client fallback"}), 200
        else:
            print("❌ Client lookup returned no match. Proceeding to guest response.")

        # ─────────────────────────────
        # Guest fallback
        # ─────────────────────────────
        print(f"🙋 Guest detected: {profile_name} ({wa_number})")
        try:
            send_whatsapp_template(
                wa_number, TEMPLATE_GUEST_WELCOME, TEMPLATE_LANG, [profile_name or "there"]
            )
            print(f"✅ Guest template sent via {TEMPLATE_GUEST_WELCOME}")
        except Exception as e:
            print(f"⚠️ Template send failed ({e}), using text fallback.")
            msg = (
                "🤖 Hello! This is the PilatesHQ Chatbot.\n\n"
                "This WhatsApp number is reserved for *registered clients* to manage bookings, reminders, and invoices.\n\n"
                "If you’d like to start Pilates or learn more, please contact *Nadine* directly 📱 084 313 1635, "
                "email 📧 lu@pilateshq.co.za, or visit 🌐 www.pilateshq.co.za 💜"
            )
            send_whatsapp_text(wa_number, msg)
        print("✅ Guest politely redirected (no lead created)")
        return jsonify({"status": "guest message"}), 200

    except Exception as e:
        print(f"❌ Webhook processing error: {e}")
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# TEST SEND + HEALTH
# ─────────────────────────────────────────────────────────────
@router_bp.route("/test_send", methods=["POST"])
def test_send():
    try:
        d = request.get_json(force=True)
        send_whatsapp_text(d.get("to"), d.get("text"))
        return jsonify({"ok": True}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@router_bp.route("/", methods=["GET"])
def health():
    return jsonify(
        {"status": "ok", "service": "PilatesHQ Booking Bot", "timeout": REQUEST_TIMEOUT}
    ), 200
