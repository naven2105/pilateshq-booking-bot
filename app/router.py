# app/router.py

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from flask import request, jsonify

from .config import (
    VERIFY_TOKEN,
    ADMIN_NUMBERS,
)
from .utils import (
    normalize_wa,
    send_whatsapp_text,
)
from .crud import (
    client_exists_by_wa,
    upsert_public_client,
    find_next_upcoming_booking_by_wa,
)

# create_cancel_request is optional; we’ll import lazily when needed
def _try_create_cancel_request(client_id: int, session_id: int) -> bool:
    try:
        from .crud import create_cancel_request  # optional table
    except Exception:
        logging.warning("[router] cancel_requests table not present; skipping queue insert.")
        return False
    try:
        _ = create_cancel_request(client_id, session_id, source="client")
        return True
    except Exception:
        logging.exception("[router] failed to insert cancel_request")
        return False


PUBLIC_MENU = (
    "✨ *PilatesHQ Info*\n"
    "1) *Address & parking* — 71 Grant Ave, Norwood (safe off-street)\n"
    "2) *Group sizes* — max 6 per class\n"
    "3) *Equipment* — Reformers, Wall Units, Wunda chairs, props, mats\n"
    "4) *Pricing* — Groups from R180\n"
    "5) *Schedule* — Weekdays 06:00–18:00; Sat 08:00–10:00\n"
    "6) *How to start* — Most begin with a 1:1 assessment\n\n"
    "• Reply *BOOK* to start a booking conversation\n"
    "• Reply *CANCEL* to request a cancellation of your next booking\n"
    "• Reply *NAME John Smith* to save/update your name"
)

FAQ_SNIPPETS = {
    "address": "📍 We’re at 71 Grant Ave, Norwood, Johannesburg. Safe off-street parking is available.",
    "parking": "🅿️ Safe off-street parking at 71 Grant Ave, Norwood.",
    "group": "👥 Group classes are capped at 6 to keep coaching personal.",
    "equipment": "🛠 We use Reformers, Wall Units, Wunda chairs, small props, and mats.",
    "pricing": "💳 Groups from R180. (Ask for the current price list if needed.)",
    "schedule": "🗓 Weekdays 06:00–18:00; Saturday 08:00–10:00.",
    "start": "➡️ Most start with a 1:1 assessment so we can tailor your plan.",
}


def _is_admin(wa: str) -> bool:
    to = normalize_wa(wa)
    return bool(to and to in {normalize_wa(n) for n in ADMIN_NUMBERS})


def _reply_menu(to: str) -> None:
    send_whatsapp_text(to, PUBLIC_MENU)


def _handle_public_message(from_wa: str, text: str) -> None:
    """
    Simple public/lead flow:
    - Always upsert a client row keyed by wa (name optional).
    - If message starts with NAME ..., update stored name.
    - Handle basic FAQs and keywords: BOOK, CANCEL.
    - Always show the menu after responding.
    """
    wa = normalize_wa(from_wa)
    if not wa:
        return

    msg = (text or "").strip()
    msg_low = msg.lower()

    # Make sure they exist in clients table (name may be NULL initially)
    if not client_exists_by_wa(wa):
        upsert_public_client(wa, None)

    # Update name if they send "NAME John Smith"
    if msg_low.startswith("name "):
        new_name = msg[5:].strip()
        if new_name:
            row = upsert_public_client(wa, new_name)
            send_whatsapp_text(wa, f"✅ Saved your name as *{row.get('name') or new_name}*.")
            _reply_menu(wa)
            return
        else:
            send_whatsapp_text(wa, "Please send your name as: *NAME Jane Doe*")
            _reply_menu(wa)
            return

    # FAQs (very lightweight matching)
    if any(k in msg_low for k in ["address", "where", "parking"]):
        send_whatsapp_text(wa, FAQ_SNIPPETS["address"])
        _reply_menu(wa)
        return
    if "group" in msg_low or "size" in msg_low:
        send_whatsapp_text(wa, FAQ_SNIPPETS["group"])
        _reply_menu(wa)
        return
    if "equip" in msg_low:
        send_whatsapp_text(wa, FAQ_SNIPPETS["equipment"])
        _reply_menu(wa)
        return
    if "price" in msg_low or "cost" in msg_low or "pay" in msg_low:
        send_whatsapp_text(wa, FAQ_SNIPPETS["pricing"])
        _reply_menu(wa)
        return
    if "schedule" in msg_low or "time" in msg_low or "open" in msg_low:
        send_whatsapp_text(wa, FAQ_SNIPPETS["schedule"])
        _reply_menu(wa)
        return
    if "start" in msg_low or "assessment" in msg_low:
        send_whatsapp_text(wa, FAQ_SNIPPETS["start"])
        _reply_menu(wa)
        return

    # Booking prompt
    if msg_low.startswith("book"):
        send_whatsapp_text(
            wa,
            "Great! To get you booked, please *NAME Your Full Name* (if not saved), "
            "and tell us your preferred day/time (e.g., *Tue 17:00*)."
        )
        _reply_menu(wa)
        return

    # Client-driven cancellation request of next upcoming session
    if msg_low.startswith("cancel"):
        nxt = find_next_upcoming_booking_by_wa(wa)
        if not nxt:
            send_whatsapp_text(wa, "You have no upcoming booking to cancel.")
            _reply_menu(wa)
            return

        created = _try_create_cancel_request(nxt["client_id"], nxt["session_id"])
        if created:
            send_whatsapp_text(wa, "✅ Cancellation request sent to admin. We’ll confirm shortly.")
        else:
            send_whatsapp_text(wa, "We’ve notified admin. They will confirm your cancellation shortly.")

        # Notify admins
        start_hhmm = str(nxt["start_time"])[:5]
        when = f"{nxt['session_date']} {start_hhmm}"
        note = f"⚠️ Cancel request from *{nxt.get('name') or 'Client'}* for *{when}*."
        for adm in ADMIN_NUMBERS:
            adm_wa = normalize_wa(adm)
            if adm_wa:
                send_whatsapp_text(adm_wa, note)

        _reply_menu(wa)
        return

    # Default: greet + menu
    send_whatsapp_text(
        wa,
        "Hi! I can share *address & parking*, *group sizes*, *equipment*, *pricing*, *schedule*, "
        "and how to *start*. You can also *BOOK* or *CANCEL*."
    )
    _reply_menu(wa)


def register_routes(app):
    """
    Register public endpoints exactly once to avoid duplicate endpoint assertion errors.
    """

    @app.get("/")
    def home():
        return "OK", 200

    @app.get("/health")
    def health():
        return jsonify({"ok": True}), 200

    # WhatsApp webhook verification (GET)
    @app.get("/webhook")
    def webhook_verify():
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token == VERIFY_TOKEN and challenge:
            return challenge, 200
        return "forbidden", 403

    # WhatsApp webhook receiver (POST)
    @app.post("/webhook")
    def webhook():
        try:
            data = request.get_json(force=True, silent=True) or {}
            # Basic structure: entry[0].changes[0].value.messages[0]
            entry = (data.get("entry") or [{}])[0]
            changes = (entry.get("changes") or [{}])[0]
            value = changes.get("value") or {}
            messages = value.get("messages") or []
            if not messages:
                return "ok", 200

            msg = messages[0]
            from_wa = msg.get("from") or ""
            wa_norm = normalize_wa(from_wa) or ""
            # Admins: we currently keep admin-only functions separate (admin.py).
            # Here we run the public flow regardless, but you can early-return if admin.
            txt = ""
            if msg.get("type") == "text":
                txt = (msg.get("text", {}) or {}).get("body", "") or ""

            # Run public flow for everyone (admins can still use admin channel/keywords elsewhere)
            _handle_public_message(wa_norm, txt)

            return "ok", 200
        except Exception:
            logging.exception("[webhook] failed")
            return "error", 500
