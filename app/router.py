# app/router.py

from __future__ import annotations

import logging
from typing import Optional, Tuple

from flask import request

from .config import ADMIN_NUMBERS, VERIFY_TOKEN
from .utils import normalize_wa, send_whatsapp_text
from .admin import handle_admin_action
from . import crud

# ──────────────────────────────────────────────────────────────────────────────
# Public (lead/FAQ) flow
# ──────────────────────────────────────────────────────────────────────────────

PUBLIC_MENU = (
    "—\n"
    "📋 *Menu*\n"
    "1) Pricing\n"
    "2) Address & parking\n"
    "3) Schedule\n"
    "4) Group sizes\n"
    "5) Equipment\n"
    "6) How to start\n"
    "7) Book (send request)\n"
    "8) Contact\n"
    "Reply with a number or keyword (e.g., *pricing*, *address*, *book*)."
)

def _public_menu() -> str:
    return PUBLIC_MENU

def _normalize(text: str) -> str:
    return (text or "").strip().lower()

def _intent_and_payload(text: str) -> Tuple[str, Optional[str]]:
    t = _normalize(text)

    # Numeric picks
    if t in {"1", "pricing", "price", "prices"}:
        return "pricing", None
    if t in {"2", "address", "parking", "where", "location"}:
        return "address", None
    if t in {"3", "schedule", "hours", "opening", "times"}:
        return "schedule", None
    if t in {"4", "group", "group sizes", "class size"}:
        return "group_sizes", None
    if t in {"5", "equipment", "machines", "reformer"}:
        return "equipment", None
    if t in {"6", "start", "how to start", "assessment"}:
        return "how_to_start", None
    if t in {"7", "book", "booking", "request"}:
        return "book_request", None
    if t in {"8", "contact", "phone", "email"}:
        return "contact", None

    # Greetings → menu
    if any(k in t for k in ["hi", "hello", "hey", "morning", "afternoon", "evening"]):
        return "menu", None

    # Keyword map
    if "price" in t or "cost" in t or "fee" in t:
        return "pricing", None
    if "address" in t or "parking" in t or "where" in t or "located" in t:
        return "address", None
    if "schedule" in t or "time" in t or "open" in t or "hour" in t:
        return "schedule", None
    if "group" in t or "size" in t:
        return "group_sizes", None
    if "equip" in t or "reformer" in t or "chair" in t or "mat" in t:
        return "equipment", None
    if "start" in t or "assessment" in t or "begin" in t:
        return "how_to_start", None
    if "book" in t or "reserve" in t:
        return "book_request", None
    if "contact" in t or "call" in t or "email" in t or "whatsapp" in t:
        return "contact", None

    return "menu", None

def _faq_response(intent: str) -> str:
    if intent == "pricing":
        return (
            "💳 *Pricing*\n"
            "• Group classes from *R180*\n"
            "• 1:1 assessment recommended for newcomers\n"
            "• Packages available – ask us for current specials"
        )
    if intent == "address":
        return (
            "📍 *Address & Parking*\n"
            "PilatesHQ — *71 Grant Ave, Norwood, Johannesburg*\n"
            "Safe off-street parking available."
        )
    if intent == "schedule":
        return (
            "🗓️ *Schedule*\n"
            "• Weekdays: 06:00–18:00\n"
            "• Saturday: 08:00–10:00\n"
            "Ask for today’s availability and we’ll suggest times."
        )
    if intent == "group_sizes":
        return (
            "👥 *Group sizes*\n"
            "Group classes are capped at *6* so coaching stays personal.\n"
            "We also offer duos and privates."
        )
    if intent == "equipment":
        return (
            "🧰 *Equipment*\n"
            "Reformers, Wall Units, Wunda Chairs, small props, and mats.\n"
            "All sessions are guided by certified instructors."
        )
    if intent == "how_to_start":
        return (
            "🚀 *How to start*\n"
            "Most clients begin with a *1:1 assessment* so we can tailor your plan.\n"
            "Reply *Book* and we’ll forward your request to the studio."
        )
    if intent == "contact":
        return (
            "☎️ *Contact*\n"
            "Prefer to chat? Message us here anytime.\n"
            "We’ll introduce you to an instructor to get started."
        )
    if intent == "book_request":
        return (
            "✅ *Booking request noted!*\n"
            "We’ve forwarded your request to the studio. An instructor will confirm time and next steps.\n"
            "If you have preferred days/times, reply with them now."
        )
    return "Thanks! How can we help today?"

def _handle_public_message(wa: str, body: str) -> None:
    # Ensure/create a lightweight client record
    try:
        if not crud.client_exists_by_wa(wa):
            crud.upsert_public_client(wa, None)
    except Exception:
        logging.exception("Lead upsert failed (non-fatal)")

    intent, _ = _intent_and_payload(body)

    # “book” → ping admin + inbox + optional leads table
    if intent == "book_request":
        response = _faq_response(intent) + "\n\n" + _public_menu()
        send_whatsapp_text(wa, response)

        # Optional: store into leads table if present; always in Inbox
        try:
            crud.lead_insert(wa, None, note=body or "")
        except Exception:
            pass

        try:
            title = "New booking request"
            inbox_body = f"From {wa}\nMessage: {body.strip() or '(no details)'}"
            crud.inbox_upsert(kind="booking_request", title=title, body=inbox_body,
                              client_id=None, session_id=None, source="whatsapp",
                              status="open", action_required=True)
        except Exception:
            logging.exception("Failed to write booking request to inbox")

        # Also nudge admins directly if you want (kept lean here)
        return

    # Normal FAQ reply
    if intent == "menu":
        send_whatsapp_text(wa, "Welcome to *PilatesHQ*! 👋\nHow can we help today?\n" + _public_menu())
    else:
        send_whatsapp_text(wa, _faq_response(intent) + "\n\n" + _public_menu())

# ──────────────────────────────────────────────────────────────────────────────
# Flask wiring
# ──────────────────────────────────────────────────────────────────────────────

def register_routes(app):
    @app.get("/")
    def root():
        return "ok", 200

    @app.get("/webhook")
    def webhook_verify():
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token == VERIFY_TOKEN and challenge:
            return challenge, 200
        return "forbidden", 403

    @app.post("/webhook")
    def webhook():
        try:
            data = request.get_json(force=True, silent=True) or {}
            entry = (data.get("entry") or [])
            if not entry: return "ok", 200
            changes = (entry[0].get("changes") or [])
            if not changes: return "ok", 200
            value = changes[0].get("value") or {}
            msgs = value.get("messages") or []
            if not msgs: return "ok", 200

            msg = msgs[0]
            from_wa_raw = msg.get("from") or ""
            from_wa = normalize_wa(from_wa_raw)
            msg_type = msg.get("type")

            # Pull text
            body = ""
            if msg_type == "text":
                body = (msg.get("text") or {}).get("body", "") or ""
            elif msg_type == "interactive":
                inter = msg.get("interactive") or {}
                if inter.get("type") == "button_reply":
                    body = (inter.get("button_reply") or {}).get("title", "") or ""
                elif inter.get("type") == "list_reply":
                    body = (inter.get("list_reply") or {}).get("title", "") or ""
                else:
                    body = ""
            else:
                body = ""

            # Route: Admin vs Public
            if from_wa in ADMIN_NUMBERS:
                # Always show admin menu after actions (inside handler)
                try:
                    handle_admin_action(from_wa, msg.get("id"), body)
                except Exception:
                    logging.exception("admin handler failed")
            else:
                _handle_public_message(from_wa, body)

            return "ok", 200

        except Exception:
            logging.exception("webhook failed")
            return "error", 500
