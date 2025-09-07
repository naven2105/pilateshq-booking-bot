# app/router.py
from __future__ import annotations

import logging
from flask import request, jsonify
from typing import Optional

from .config import VERIFY_TOKEN, ADMIN_NUMBERS
from .utils import normalize_wa, send_whatsapp_text
from .crud import client_exists_by_wa, upsert_public_client, find_next_upcoming_booking_by_wa

def _is_admin(wa: str) -> bool:
    wa_n = normalize_wa(wa)
    return bool(wa_n and wa_n in {normalize_wa(n) for n in ADMIN_NUMBERS})

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

def _reply_menu(to: str) -> None:
    send_whatsapp_text(to, PUBLIC_MENU)

def _try_create_cancel_request(client_id: int, session_id: int) -> bool:
    try:
        from .crud import create_cancel_request
    except Exception:
        logging.warning("[router] cancel_requests table not present; skipping queue insert.")
        return False
    try:
        create_cancel_request(client_id, session_id, source="client")
        return True
    except Exception:
        logging.exception("[router] failed to insert cancel_request")
        return False

def _handle_public_message(from_wa: str, text: str) -> None:
    wa = normalize_wa(from_wa)
    if not wa:
        return
    msg = (text or "").strip()
    low = msg.lower()

    # Ensure a client row exists
    if not client_exists_by_wa(wa):
        upsert_public_client(wa, None)

    # NAME update
    if low.startswith("name "):
        new_name = msg[5:].strip()
        if new_name:
            row = upsert_public_client(wa, new_name)
            send_whatsapp_text(wa, f"✅ Saved your name as *{row.get('name') or new_name}*.")
        else:
            send_whatsapp_text(wa, "Please send your name as: *NAME Jane Doe*")
        _reply_menu(wa)
        return

    # FAQs
    if any(k in low for k in ["address", "where", "parking"]):
        send_whatsapp_text(wa, FAQ_SNIPPETS["address"]); _reply_menu(wa); return
    if "group" in low or "size" in low:
        send_whatsapp_text(wa, FAQ_SNIPPETS["group"]); _reply_menu(wa); return
    if "equip" in low:
        send_whatsapp_text(wa, FAQ_SNIPPETS["equipment"]); _reply_menu(wa); return
    if "price" in low or "cost" in low or "pay" in low:
        send_whatsapp_text(wa, FAQ_SNIPPETS["pricing"]); _reply_menu(wa); return
    if "schedule" in low or "time" in low or "open" in low:
        send_whatsapp_text(wa, FAQ_SNIPPETS["schedule"]); _reply_menu(wa); return
    if "start" in low or "assessment" in low:
        send_whatsapp_text(wa, FAQ_SNIPPETS["start"]); _reply_menu(wa); return

    # Booking prompt
    if low.startswith("book"):
        send_whatsapp_text(
            wa,
            "Great! To get you booked, please *NAME Your Full Name* (if not saved), "
            "and tell us your preferred day/time (e.g., *Tue 17:00*)."
        )
        _reply_menu(wa)
        return

    # Client cancel request of next upcoming booking
    if low.startswith("cancel"):
        nxt = find_next_upcoming_booking_by_wa(wa)
        if not nxt:
            send_whatsapp_text(wa, "You have no upcoming booking to cancel.")
            _reply_menu(wa); return

        created = _try_create_cancel_request(nxt["client_id"], nxt["session_id"])
        if created:
            send_whatsapp_text(wa, "✅ Cancellation request sent to admin. We’ll confirm shortly.")
        else:
            send_whatsapp_text(wa, "We’ve notified admin. They will confirm your cancellation shortly.")

        when = f"{nxt['session_date']} {str(nxt['start_time'])[:5]}"
        note = f"⚠️ Cancel request from *{nxt.get('name') or 'Client'}* for *{when}*."
        for adm in ADMIN_NUMBERS:
            adm_wa = normalize_wa(adm)
            if adm_wa:
                send_whatsapp_text(adm_wa, note)
        _reply_menu(wa); return

    # Default greeting
    send_whatsapp_text(
        wa,
        "Hi! I can share *address & parking*, *group sizes*, *equipment*, *pricing*, *schedule*, "
        "and how to *start*. You can also *BOOK* or *CANCEL*."
    )
    _reply_menu(wa)

def register_routes(app):
    # Use add_url_rule + guards so we never overwrite existing endpoints
    if "home" not in app.view_functions:
        def home():
            return "OK", 200
        app.add_url_rule("/", endpoint="home", view_func=home, methods=["GET"])

    if "health" not in app.view_functions:
        def health():
            return jsonify({"ok": True}), 200
        app.add_url_rule("/health", endpoint="health", view_func=health, methods=["GET"])

    if "webhook_verify" not in app.view_functions:
        def webhook_verify():
            mode = request.args.get("hub.mode")
            token = request.args.get("hub.verify_token")
            challenge = request.args.get("hub.challenge")
            if mode == "subscribe" and token == VERIFY_TOKEN and challenge:
                return challenge, 200
            return "forbidden", 403
        app.add_url_rule("/webhook", endpoint="webhook_verify", view_func=webhook_verify, methods=["GET"])

    if "webhook" not in app.view_functions:
        def webhook():
            try:
                data = request.get_json(force=True, silent=True) or {}
                entry = (data.get("entry") or [{}])[0]
                changes = (entry.get("changes") or [{}])[0]
                value = changes.get("value") or {}
                messages = value.get("messages") or []
                if not messages:
                    return "ok", 200

                msg = messages[0]
                from_wa = normalize_wa(msg.get("from") or "")
                body = ""
                if msg.get("type") == "text":
                    body = (msg.get("text") or {}).get("body", "") or ""

                # Run public flow for all inbound (admin flow lives elsewhere if needed)
                if from_wa:
                    _handle_public_message(from_wa, body)
                return "ok", 200
            except Exception:
                logging.exception("[webhook] failed")
                return "error", 500
        app.add_url_rule("/webhook", endpoint="webhook", view_func=webhook, methods=["POST"])
