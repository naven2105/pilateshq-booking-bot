from flask import Flask, request
import os
import logging
from datetime import datetime

from booking import handle_booking_message
from wellness import handle_wellness_message
from utils import send_whatsapp_list
from db import init_db
from crud import list_available_slots, hold_or_reserve_slot, release_slot  # NEW

app = Flask(__name__)

# Env
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "your_verify_token_here")
NADINE_WA = os.environ.get("NADINE_WA", "27843131635")  # SA format w/out '+'

# Logging
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, log_level))

# ---- One-time DB init ----
_db_inited = False
@app.before_request
def startup_db_once():
    global _db_inited
    if not _db_inited:
        try:
            init_db()
            logging.info("✅ DB initialised / verified")
        except Exception as e:
            logging.exception("❌ DB init failed", exc_info=True)
        _db_inited = True

# ---- Health ----
@app.route("/", methods=["GET"])
def home():
    return "OK", 200

# ---- Webhook verify ----
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    mode = request.args.get("hub.mode")
    logging.info(f"[VERIFY] mode={mode}")
    if token == VERIFY_TOKEN:
        logging.info("[VERIFY] success")
        return challenge, 200
    logging.warning("[VERIFY] failed")
    return "Verification failed", 403

# ---- Webhook POST ----
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    logging.debug(f"[WEBHOOK DATA] {data}")

    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                messages = value.get("messages", [])
                for message in messages:
                    sender = message["from"]

                    # Interactive replies (list)
                    if message.get("type") == "interactive":
                        inter = message.get("interactive", {})
                        reply_id = ""
                        if "button_reply" in inter:
                            reply_id = inter["button_reply"]["id"]
                        elif "list_reply" in inter:
                            reply_id = inter["list_reply"]["id"]
                        reply_id = (reply_id or "").strip().upper()
                        logging.info(f"[CLICK] {sender} -> {reply_id}")
                        route_message(sender, reply_id)
                        continue

                    # Text messages
                    if message.get("type") == "text":
                        text = (message.get("text", {}).get("body") or "").strip().upper()
                        logging.info(f"[TEXT] {sender} -> {text}")
                        route_message(sender, text)
                        continue

    except Exception as e:
        logging.exception(f"[ERROR webhook]: {e}")

    return "ok", 200

# ---- Router ----
def route_message(sender: str, text: str):
    # Greetings / menu
    if text in ("MENU", "MAIN_MENU", "HI", "HELLO", "START"):
        send_intro_and_menu(sender)
        return

    # Wellness
    if text == "WELLNESS" or text.startswith("WELLNESS_"):
        handle_wellness_message(text, sender)
        return

    # Booking (old flow still available)
    if (
        text == "BOOK"
        or text in ("GROUP", "DUO", "SINGLE")
        or text.startswith(("DAY_", "TIME_", "PERIOD_"))
    ):
        handle_booking_message(text, sender)
        return

    # New: Availability browse
    if text in ("AVAIL", "AVAILABILITY", "VIEW_AVAIL"):
        show_availability(sender)
        return

    # A slot was tapped: SLOT_<id>
    if text.startswith("SLOT_"):
        session_id = safe_int(text.replace("SLOT_", ""))
        if not session_id:
            send_intro_and_menu(sender); return
        handle_slot_selection(sender, session_id)
        return

    # Nadine admin actions
    if text.startswith("APPROVE_") and is_nadine(sender):
        session_id = safe_int(text.replace("APPROVE_", ""))
        # For now, "approve" keeps the hold; later we can create a Booking row
        confirm_admin_action(sender, session_id, approved=True)
        return

    if text.startswith("RELEASE_") and is_nadine(sender):
        session_id = safe_int(text.replace("RELEASE_", ""))
        if session_id:
            release_slot(session_id, seats=1)
        notify_admin_simple(f"🔓 Released hold | Session {session_id}")
        return

    # Default
    send_intro_and_menu(sender)

# ---- UI blocks ----
def send_intro_and_menu(recipient: str):
    intro = (
        "✨ Welcome to PilatesHQ ✨\n\n"
        "Transformative Pilates in Norwood, Johannesburg.\n"
        "🎉 Opening Special: Group Classes @ R180 until January\n"
        "🌐 https://pilateshq.co.za"
    )
    send_whatsapp_list(
        recipient,
        header="PilatesHQ",
        body=intro + "\n\nPlease choose an option:",
        button_id="MAIN_MENU",
        options=[
            {"id": "AVAIL", "title": "👀 View Availability"},
            {"id": "WELLNESS", "title": "💡 Wellness Tips"},
            {"id": "BOOK", "title": "🧭 Legacy Booking"},  # optional, can remove later
        ],
    )

def show_availability(recipient: str):
    """Pull up to 10 open sessions (≥1 seat)."""
    rows = list_available_slots(days=21, min_seats=1, limit=10)
    if not rows:
        send_whatsapp_list(
            recipient, "Availability", "No open sessions found. Please check again soon.",
            "MAIN_MENU", [{"id": "MAIN_MENU", "title": "⬅️ Back to Menu"}]
        )
        return

    # Build list rows (≤ 10)
    options = []
    for r in rows:
        # Format like: Mon 25 Aug • 07:00 • 3 left
        dt_label = f"{fmt_date(r['session_date'])} • {fmt_time(r['start_time'])} • {r['seats_left']} left"
        options.append({"id": f"SLOT_{r['id']}", "title": dt_label[:24], "description": "Tap to request this slot"})

    send_whatsapp_list(
        recipient,
        header="Available Slots",
        body="Select a slot to request it. Nadine will review and confirm.",
        button_id="AVAIL_LIST",
        options=options
    )

def handle_slot_selection(sender: str, session_id: int):
    """Place a soft hold and notify Nadine with admin choices."""
    updated = hold_or_reserve_slot(session_id, seats=1)
    if not updated:
        # Likely full or race condition
        send_whatsapp_list(
            sender, "Unavailable", "Sorry, that slot just filled. Try another.",
            "AVAIL_RETRY", [{"id": "AVAIL", "title": "👀 View Availability"}]
        )
        return

    # Confirm to client
    body = (
        "✅ Request received! Nadine will review and confirm your spot.\n\n"
        f"🗓 {fmt_date(updated['session_date'])} at {fmt_time(updated['start_time'])}\n"
        f"Seats left: {updated['capacity'] - updated['booked_count']}"
    )
    send_whatsapp_list(
        sender, "Request Submitted", body,
        "REQ_MENU", [{"id": "MAIN_MENU", "title": "⬅️ Back to Menu"}]
    )

    # Notify Nadine (admin)
    admin_text = (
        "📣 Booking Request\n"
        f"From: {sender}\n"
        f"Time: {fmt_date(updated['session_date'])} {fmt_time(updated['start_time'])}\n"
        f"Status: {updated['status']} • Seats left: {updated['capacity'] - updated['booked_count']}\n\n"
        "Action:"
    )
    send_whatsapp_list(
        NADINE_WA,
        header="Admin: Approve?",
        body=admin_text,
        button_id="ADMIN_ACTION",
        options=[
            {"id": f"APPROVE_{session_id}", "title": "✅ Approve"},
            {"id": f"RELEASE_{session_id}", "title": "🔓 Release"},
            {"id": "MAIN_MENU", "title": "⬅️ Menu"},
        ]
    )

def confirm_admin_action(sender: str, session_id: int, approved: bool):
    # Placeholder: later we’ll create a Booking row + DM client confirmation.
    if approved:
        notify_admin_simple(f"✅ Approved hold | Session {session_id}")
    else:
        notify_admin_simple(f"Declined | Session {session_id}")

def notify_admin_simple(msg: str):
    send_whatsapp_list(
        NADINE_WA, "Admin", msg, "ADMIN_MENU",
        [{"id": "MAIN_MENU", "title": "⬅️ Menu"}]
    )

# ---- helpers ----
def is_nadine(wa_from: str) -> bool:
    # Incoming `From` is like "2784..." (no '+')
    return wa_from.strip().lstrip("+") == NADINE_WA

def safe_int(s: str):
    try:
        return int(s)
    except Exception:
        return None

def fmt_date(d) -> str:
    # d can be date or str
    if isinstance(d, str):
        try:
            d = datetime.fromisoformat(d).date()
        except Exception:
            return d
    return d.strftime("%a %d %b")

def fmt_time(t) -> str:
    # t can be time or str
    if isinstance(t, str):
        try:
            return datetime.fromisoformat(f"2000-01-01T{t}").strftime("%H:%M")
        except Exception:
            return t
    return t.strftime("%H:%M")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
