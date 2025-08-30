# app/admin.py
"""
Admin flows & state machine for WhatsApp (Nadine).
Supports single-word intents (NEW/UPDATE/CANCEL/VIEW/BOOK/NOTIFY),
interactive lists/buttons, free-text capture, and NLP fallbacks.

Key ideas:
- Each admin (by WA number) has a small in-memory state (ADMIN_STATE)
  to drive multi-step wizards.
- All outbound messages go through utils.* (Meta WhatsApp Cloud API).
- All DB reads/writes funnel through crud.* (thin SQL helpers) or booking.*.
"""

import os
import re
import logging
from datetime import date
from urllib.parse import quote, unquote

from sqlalchemy import text

from .utils import (
    send_whatsapp_list,
    send_whatsapp_text,
    send_whatsapp_buttons,
    normalize_wa,
)
from . import crud
from . import booking
from .db import get_session
from .admin_nlp import parse_admin_command, parse_admin_client_command

# ──────────────────────────────────────────────────────────────────────────────
# Admin authentication
# ──────────────────────────────────────────────────────────────────────────────
ADMIN_WA_LIST = [n.strip() for n in os.getenv("ADMIN_WA_LIST", "").split(",") if n.strip()]
NADINE_WA = os.getenv("NADINE_WA", "").strip()

def _is_admin(sender: str) -> bool:
    """Check if the sender’s number is allowed to use admin functions."""
    wa = normalize_wa(sender)
    allow = set(normalize_wa(x) for x in ADMIN_WA_LIST if x)
    if NADINE_WA:
        allow.add(normalize_wa(NADINE_WA))
    ok = wa in allow
    logging.debug(f"[ADMIN AUTH] sender={wa} allow={sorted(list(allow))} ok={ok}")
    return ok

# ──────────────────────────────────────────────────────────────────────────────
# Flows, awaits, and in-memory state
# ──────────────────────────────────────────────────────────────────────────────
FLOWS = {"NEW", "UPDATE", "CANCEL", "VIEW", "BOOK", "NOTIFY"}
AWAIT_FIELDS = {"NAME", "PHONE", "DOB", "PLAN", "MEDICAL", "CREDITS", "CUSTOM_BROADCAST"}
BOOK_TYPES = {"single", "duo", "group"}
BOOK_MODES = {"one", "ongoing"}

# Per-admin state store:
#   ADMIN_STATE["+27..."] = {
#       "flow": "NEW"/"UPDATE"/...,
#       "await": "NAME"/"DOB"/.../None,
#       "cid": int|None,
#       "buffer": dict,      # temporary answers (NEW wizard)
#       "book": dict,        # {type, mode, slot_id}
#   }
ADMIN_STATE: dict[str, dict] = {}

def _get_state(wa: str) -> dict:
    """Return mutable state for this admin; always has required keys."""
    st = ADMIN_STATE.get(wa)
    if not st:
        st = {"flow": None, "await": None, "cid": None, "buffer": {}, "book": {}}
        ADMIN_STATE[wa] = st
    st.setdefault("buffer", {})
    st.setdefault("book", {})
    return st

def _set_state(wa: str, **updates):
    """Update admin state with logging of the transition."""
    st = _get_state(wa)
    before = {k: st.get(k) for k in ("flow", "await", "cid")}
    st.update(updates)
    after = {k: st.get(k) for k in ("flow", "await", "cid")}
    logging.debug("[ADMIN STATE] %s BEFORE=%s AFTER=%s", wa, before, after)
    return st

def _require_client_selected(wa: str, st: dict, action_hint: str):
    """Ensure a client is selected; otherwise guide the admin back to picker."""
    if not st.get("cid"):
        logging.debug("[ADMIN GUARD] %s requires client but none selected", action_hint)
        return _client_picker(wa, f"{action_hint}: pick client")
    return None

# ──────────────────────────────────────────────────────────────────────────────
# Menus
# ──────────────────────────────────────────────────────────────────────────────
def _root_menu(to: str):
    """Main admin menu (entry point)."""
    return send_whatsapp_list(
        to, "Admin", "Type a single word to start or tap:", "ADMIN_ROOT",
        [
            {"id": "ADMIN_INTENT_NEW",    "title": "➕ New"},
            {"id": "ADMIN_INTENT_UPDATE", "title": "✏️ Update"},
            {"id": "ADMIN_INTENT_CANCEL", "title": "❌ Cancel"},
            {"id": "ADMIN_INTENT_VIEW",   "title": "👁️ View"},
            {"id": "ADMIN_INTENT_BOOK",   "title": "📅 Book"},
            {"id": "ADMIN_INTENT_NOTIFY", "title": "📢 Notify"},
        ],
    )

def _client_picker(to: str, title="Clients", q: str | None = None):
    """List clients for selection (update/cancel/view/book)."""
    if q:
        matches = crud.find_clients_by_name(q, limit=10)
    else:
        matches = crud.list_clients(limit=10)

    rows = []
    for c in matches:
        rows.append({
            "id": f"ADMIN_PICK_CLIENT_{c['id']}",
            "title": (c["name"] or "(no name)")[:24],
            "description": f"{c['wa_number']} • {c.get('credits',0)} cr"
        })

    body = "Pick a client:" + (f' (search="{q}")' if q else "")
    return send_whatsapp_list(to, title, body, "ADMIN_CLIENTS", rows or [{"id": "ADMIN_ROOT", "title": "⬅️ Back"}])

def _show_profile(to: str, cid: int):
    """Display a client profile (name, wa, plan, credits, DOB, notes)."""
    prof = crud.get_client_profile(cid)
    if not prof:
        return send_whatsapp_text(to, "Client not found.")

    bday = f"{(prof.get('birthday_day') or '')}-{(prof.get('birthday_month') or '')}".strip("-")
    text = (f"👤 {prof['name']}\n"
            f"📱 {prof['wa_number']}\n"
            f"📅 Plan: {prof.get('plan','')}\n"
            f"🎟️ Credits: {prof.get('credits',0)}\n"
            f"🎂 DOB: {bday or '—'}\n"
            f"📝 Notes: {prof.get('medical_notes') or '—'}")
    return send_whatsapp_text(to, text)

def _update_menu(to: str, cid: int):
    """Show update menu with editable fields for the chosen client."""
    prof = crud.get_client_profile(cid)
    if not prof:
        return send_whatsapp_text(to, "Client not found.")
    return send_whatsapp_list(
        to, "Update Client", f"Edit fields for {prof['name']}:", "ADMIN_UPDATE",
        [
            {"id": "ADMIN_EDIT_NAME",    "title": "👤 Name"},
            {"id": "ADMIN_EDIT_DOB",     "title": "🎂 DOB"},
            {"id": "ADMIN_EDIT_PLAN",    "title": "📅 Plan"},
            {"id": "ADMIN_EDIT_MEDICAL", "title": "🩺 Medical Notes"},
            {"id": "ADMIN_EDIT_CREDITS", "title": "🎟️ Credits (+/-)"},
            {"id": "ADMIN_DONE",         "title": "✅ Done"},
        ],
    )

def _ask_free_text(to: str, header: str, prompt: str, back_id="ADMIN_INTENT_UPDATE"):
    """Prompt admin to reply with free-text (for name/notes/dob/plan/credits)."""
    return send_whatsapp_list(
        to, header, prompt, "ADMIN_BACK",
        [{"id": back_id, "title": "⬅️ Back"}]
    )

# ──────────────────────────────────────────────────────────────────────────────
# Small DB helpers
# ──────────────────────────────────────────────────────────────────────────────
def _save_name(cid: int, name: str):
    with get_session() as s:
        s.execute(text("UPDATE clients SET name=:nm WHERE id=:cid"),
                  {"nm": name[:120], "cid": cid})

def _save_plan(cid: int, plan: str):
    with get_session() as s:
        s.execute(text("UPDATE clients SET plan=:p WHERE id=:cid"),
                  {"p": plan[:20], "cid": cid})

def _save_credits_delta(cid: int, delta: int):
    crud.adjust_client_credits(cid, delta)

# ──────────────────────────────────────────────────────────────────────────────
# Booking menus
# ──────────────────────────────────────────────────────────────────────────────
def _book_type_menu(to: str):
    return send_whatsapp_list(
        to, "Booking", "Pick session type:", "ADMIN_BOOK",
        [
            {"id": "ADMIN_BOOK_TYPE_single", "title": "Single"},
            {"id": "ADMIN_BOOK_TYPE_duo",    "title": "Duo"},
            {"id": "ADMIN_BOOK_TYPE_group",  "title": "Group"},
        ],
    )

def _book_mode_menu(to: str):
    return send_whatsapp_list(
        to, "Booking", "One-off or ongoing?", "ADMIN_BOOK",
        [
            {"id": "ADMIN_BOOK_MODE_one",     "title": "One-off"},
            {"id": "ADMIN_BOOK_MODE_ongoing", "title": "Ongoing"},
        ],
    )

def _book_slot_menu(to: str):
    slots = booking.list_next_open_slots(limit=10)
    rows = []
    for s in slots:
        rows.append({
            "id": f"ADMIN_BOOK_SLOT_{s['id']}",
            "title": f"{s['session_date']} {s['start_time']}",
            "description": f"{s['seats_left']} open"
        })
    return send_whatsapp_list(
        to, "Pick a slot", "Next open sessions:", "ADMIN_BOOK_SLOTS",
        rows or [{"id": "ADMIN_ROOT", "title": "⬅️ Back"}]
    )

# ──────────────────────────────────────────────────────────────────────────────
# Notify / Broadcast helpers
# ──────────────────────────────────────────────────────────────────────────────
def _notify_menu(to: str):
    return send_whatsapp_list(
        to, "Notify Clients", "Send a message to all clients:", "ADMIN_NOTIFY",
        [
            {"id": "ADMIN_NOTIFY_OFFSICK", "title": "🤒 Off Sick Today"},
            {"id": "ADMIN_NOTIFY_CUSTOM",  "title": "✍️ Custom Broadcast"},
            {"id": "ADMIN_DONE",           "title": "✅ Done"},
        ],
    )

def _broadcast_to_all(body: str) -> int:
    """
    Sends `body` to every client that has a wa_number.
    Returns how many messages were sent.
    """
    sent = 0
    with get_session() as s:
        rows = s.execute(text("""
            SELECT DISTINCT wa_number
            FROM clients
            WHERE wa_number IS NOT NULL AND trim(wa_number) <> ''
        """)).all()
    seen = set()
    for (wa,) in rows:
        n = normalize_wa(wa)
        if not n or n in seen:
            continue
        seen.add(n)
        send_whatsapp_text(n, body)
        sent += 1
    logging.info(f"[BROADCAST] sent={sent}")
    return sent

# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────
def handle_admin_action(sender: str, text: str):
    """
    Main dispatcher.
    Decides what to do based on current state, incoming text
    (interactive button ID or free text), and NLP fallbacks.
    """
    try:
        if not _is_admin(sender):
            return send_whatsapp_text(sender, "⛔ Only Nadine (admin) can perform admin functions.")

        wa = normalize_wa(sender)
        st = _get_state(wa)

        raw = (text or "").strip()
        up = raw.upper()
        logging.info("[ADMIN CMD] wa=%s raw=%r up=%r flow=%s await=%s cid=%s",
                     wa, raw, up, st["flow"], st["await"], st["cid"])

        # ── Intent shortcuts (interactive buttons or typing the word)
        if up in ("ADMIN_INTENT_NEW", "NEW"):
            _set_state(wa, flow="NEW", await=None, cid=None, buffer={}, book={})
            return _start_new(wa, st)
        if up in ("ADMIN_INTENT_UPDATE", "UPDATE"):
            _set_state(wa, flow="UPDATE", await=None)
            return _client_picker(wa, "Update: pick client")
        if up in ("ADMIN_INTENT_CANCEL", "CANCEL"):
            _set_state(wa, flow="CANCEL", await=None)
            return _client_picker(wa, "Cancel: pick client")
        if up in ("ADMIN_INTENT_VIEW", "VIEW"):
            _set_state(wa, flow="VIEW", await=None)
            return _client_picker(wa, "View: pick client")
        if up in ("ADMIN_INTENT_BOOK", "BOOK"):
            _set_state(wa, flow="BOOK", await=None)
            return _client_picker(wa, "Book: pick client")
        if up in ("ADMIN_INTENT_NOTIFY", "NOTIFY"):
            _set_state(wa, flow="NOTIFY", await=None)
            return _notify_menu(wa)

        # ── Client selected from list
        if up.startswith("ADMIN_PICK_CLIENT_"):
            cid_part = up.replace("ADMIN_PICK_CLIENT_", "")
            try:
                cid = int(cid_part)
            except ValueError:
                logging.warning("[ADMIN] invalid client id in selection: %r", cid_part)
                return send_whatsapp_text(wa, "⚠️ Invalid selection.")
            _set_state(wa, cid=cid)
            if st["flow"] == "VIEW":
                return _show_profile(wa, cid)
            if st["flow"] == "UPDATE":
                return _update_menu(wa, cid)
            if st["flow"] == "CANCEL":
                # TODO: wire actual cancel helper; keep user-friendly stub
                return send_whatsapp_text(wa, "Use UPDATE/BOOK flows until cancel-by-client is wired to CRUD.")
            if st["flow"] == "BOOK":
                return _book_type_menu(wa)
            return _root_menu(wa)

        # ── UPDATE: choose field to edit
        if up in ("ADMIN_EDIT_NAME", "ADMIN_EDIT_DOB", "ADMIN_EDIT_PLAN", "ADMIN_EDIT_MEDICAL", "ADMIN_EDIT_CREDITS"):
            need = _require_client_selected(wa, st, "Update")
            if need: return need
            mapping = {
                "ADMIN_EDIT_NAME":    ("NAME",    "Edit Name",          "Reply with the client's full name."),
                "ADMIN_EDIT_DOB":     ("DOB",     "Edit DOB",           "Reply as DD MON (e.g., 21 MAY)."),
                "ADMIN_EDIT_PLAN":    ("PLAN",    "Edit Plan",          "Reply with: 1x, 2x, or 3x."),
                "ADMIN_EDIT_MEDICAL": ("MEDICAL", "Edit Medical Notes", "Reply with the medical note (replaces existing)."),
                "ADMIN_EDIT_CREDITS": ("CREDITS", "Adjust Credits",     "Reply with +N or -N (e.g., +1, -2)."),
            }
            field, hdr, prompt = mapping[up]
            _set_state(wa, await=field)
            return _ask_free_text(wa, hdr, prompt)

        if up == "ADMIN_DONE":
            _set_state(wa, flow=None, await=None, cid=None)
            st["buffer"].clear(); st["book"].clear()
            return _root_menu(wa)

        # ── BOOK: type/mode/slot/confirm
        if up.startswith("ADMIN_BOOK_TYPE_"):
            need = _require_client_selected(wa, st, "Book")
            if need: return need
            t = up.replace("ADMIN_BOOK_TYPE_", "").lower()
            if t not in BOOK_TYPES:
                logging.warning("[ADMIN BOOK] invalid type=%r", t)
                return send_whatsapp_text(wa, "⚠️ Invalid type.")
            st["book"]["type"] = t
            logging.debug("[ADMIN BOOK] type=%s", t)
            return _book_mode_menu(wa)

        if up.startswith("ADMIN_BOOK_MODE_"):
            need = _require_client_selected(wa, st, "Book")
            if need: return need
            m = up.replace("ADMIN_BOOK_MODE_", "").lower()
            if m not in BOOK_MODES:
                logging.warning("[ADMIN BOOK] invalid mode=%r", m)
                return send_whatsapp_text(wa, "⚠️ Invalid mode.")
            st["book"]["mode"] = m
            logging.debug("[ADMIN BOOK] mode=%s", m)
            return _book_slot_menu(wa)

        if up.startswith("ADMIN_BOOK_SLOT_"):
            need = _require_client_selected(wa, st, "Book")
            if need: return need
            slot_part = up.replace("ADMIN_BOOK_SLOT_", "")
            try:
                slot_id = int(slot_part)
            except ValueError:
                logging.warning("[ADMIN BOOK] invalid slot id=%r", slot_part)
                return send_whatsapp_text(wa, "⚠️ Invalid slot.")
            st["book"]["slot_id"] = slot_id
            prof = crud.get_client_profile(st["cid"])
            nm = prof["name"] if prof else "client"
            body = f"Confirm booking for {nm}\n• Type: {st['book'].get('type')}\n• Mode: {st['book'].get('mode')}\n• Slot ID: {slot_id}"
            return send_whatsapp_buttons(wa, body, [
                {"id": "ADMIN_BOOK_CONFIRM", "title": "Confirm"},
                {"id": "ADMIN_INTENT_BOOK",  "title": "Back"},
            ])

        if up == "ADMIN_BOOK_CONFIRM":
            need = _require_client_selected(wa, st, "Book")
            if need: return need
            slot_id = st.get("book", {}).get("slot_id")
            if not slot_id:
                logging.warning("[ADMIN BOOK] confirm without slot")
                return send_whatsapp_text(wa, "⚠️ Missing slot selection.")
            prof = crud.get_client_profile(st["cid"])
            ok = booking.admin_reserve(prof["wa_number"], slot_id, seats=1)
            logging.info("[ADMIN BOOK] reserve cid=%s slot=%s ok=%s", st["cid"], slot_id, ok)
            send_whatsapp_text(wa, "✅ Booked." if ok else "⚠️ Could not book (full?).")
            st["book"] = {}  # keep client selected for follow-up edits
            return _update_menu(wa, st["cid"])

        # ── NOTIFY flow
        if up == "ADMIN_NOTIFY_OFFSICK":
            today = date.today().isoformat()
            body = (
                f"Hi! Nadine here from PilatesHQ.\n"
                f"Unfortunately I’m off sick today ({today}) 🤒\n"
                f"All sessions today are cancelled. I’ll follow up to reschedule.\n"
                f"Thanks for understanding!"
            )
            count = _broadcast_to_all(body)
            return send_whatsapp_text(wa, f"✅ Sent off-sick notice to {count} clients.")

        if up == "ADMIN_NOTIFY_CUSTOM":
            _set_state(wa, await="CUSTOM_BROADCAST")
            return _ask_free_text(
                wa,
                "Custom Broadcast",
                "Reply with the message to send to *all clients*.\nTip: Keep it short and clear.",
                back_id="ADMIN_INTENT_NOTIFY",
            )

        # ── NEW wizard “next” button (internal)
        if up == "ADMIN_NEW_NEXT":
            return _new_next(wa, st)

        # ── Free text for whichever field we’re awaiting
        if st.get("await"):
            logging.debug("[ADMIN CAPTURE] await=%s raw=%r", st["await"], raw)
            return _capture_free_text(wa, st, raw)

        # ── NLP fallback (when not inside a wizard capture)
        nlp = parse_admin_client_command(raw) or parse_admin_command(raw)
        logging.debug("[ADMIN NLP] raw=%r parsed=%s", raw, nlp)
        if nlp:
            intent = nlp.get("intent")
            if intent == "add_client":
                res = crud.create_client(nlp["name"], normalize_wa(nlp["number"]))
                return send_whatsapp_text(wa, "✅ Client added." if res else "⚠️ Could not add client.")
            if intent == "update_dob":
                match = crud.find_clients_by_name(nlp["name"], limit=1)
                if not match: return send_whatsapp_text(wa, "⚠️ No client found.")
                crud.update_client_dob(match[0]["id"], int(nlp["day"]), int(nlp["month"]))
                return send_whatsapp_text(wa, "✅ DOB updated.")
            if intent == "update_medical":
                match = crud.find_clients_by_name(nlp["name"], limit=1)
                if not match: return send_whatsapp_text(wa, "⚠️ No client found.")
                crud.update_client_medical(match[0]["id"], nlp["note"], append=True)
                return send_whatsapp_text(wa, "✅ Note added.")
            if intent == "cancel_next":
                match = crud.find_clients_by_name(nlp["name"], limit=1)
                if not match: return send_whatsapp_text(wa, "⚠️ No client found.")
                ok = getattr(crud, "cancel_next_booking_for_client", lambda *_: False)(match[0]["id"])
                return send_whatsapp_text(wa, "✅ Next session cancelled." if ok else "⚠️ No upcoming booking found.")
            if intent == "off_sick_today":
                # Optional: wire an “excused” status per-session if you have it
                return send_whatsapp_text(wa, "✅ Noted off sick (stub).")
            if intent == "no_show_today":
                match = crud.find_clients_by_name(nlp["name"], limit=1)
                if not match: return send_whatsapp_text(wa, "⚠️ No client found.")
                ok = getattr(crud, "mark_no_show_today", lambda *_: False)(match[0]["id"])
                return send_whatsapp_text(wa, "✅ No-show recorded." if ok else "⚠️ No booking found today.")
            if intent == "book_single":
                sess = getattr(crud, "find_session_by_date_time", lambda *_: None)(date.fromisoformat(nlp["date"]), nlp["time"])
                if not sess: return send_whatsapp_text(wa, "⚠️ No matching session found.")
                match = crud.find_clients_by_name(nlp["name"], limit=1)
                if not match: return send_whatsapp_text(wa, "⚠️ No client found.")
                prof = crud.get_client_profile(match[0]["id"])
                ok = booking.admin_reserve(prof["wa_number"], sess["id"], seats=1)
                return send_whatsapp_text(wa, "✅ Booked." if ok else "⚠️ Could not book (full?).")
            if intent == "book_recurring":
                # Stub: loop N weeks, locate sessions per week, reserve seats
                return send_whatsapp_text(wa, "✅ Recurring booking stub (wire your weekly finder).")

        # Default: show root
        return _root_menu(wa)

    except Exception as e:
        logging.exception("[ADMIN ERROR] unhandled error: %s", e)
        return send_whatsapp_text(sender, "⚠️ Something went wrong while processing your request.")

# ──────────────────────────────────────────────────────────────────────────────
# NEW CLIENT WIZARD
# ──────────────────────────────────────────────────────────────────────────────
def _start_new(wa: str, st: dict):
    """Begin the new-client wizard (NAME → PHONE → PLAN → DOB → MEDICAL)."""
    _set_state(wa, await="NAME", buffer={}, cid=None)
    return _ask_free_text(wa, "New Client", "Reply with the client's full name.", "ADMIN_INTENT_NEW")

def _new_next(wa: str, st: dict):
    """Advance the new-client wizard to the next field."""
    step = st.get("await")
    buf = st.get("buffer", {})
    if step == "NAME":
        _set_state(wa, await="PHONE")
        return _ask_free_text(wa, "New Client", "Reply with the client's phone (0XXXXXXXXX, +27…, or 27…).", "ADMIN_INTENT_NEW")
    if step == "PHONE":
        _set_state(wa, await="PLAN")
        return _ask_free_text(wa, "New Client", "Reply with plan: 1x, 2x, or 3x.", "ADMIN_INTENT_NEW")
    if step == "PLAN":
        _set_state(wa, await="DOB")
        return _ask_free_text(wa, "New Client", "Reply DOB as DD MON (e.g., 21 MAY).", "ADMIN_INTENT_NEW")
    if step == "DOB":
        _set_state(wa, await="MEDICAL")
        return _ask_free_text(wa, "New Client", "Medical notes (optional). Reply '-' to skip.", "ADMIN_INTENT_NEW")
    if step == "MEDICAL":
        # Persist all fields now
        name = (buf.get("NAME") or "").strip()
        phone = normalize_wa(buf.get("PHONE") or "")
        plan = (buf.get("PLAN") or "").lower()
        day, mon = buf.get("DOB_DAY"), buf.get("DOB_MON")
        medical = (buf.get("MEDICAL") or "").strip()

        row = crud.create_client(name, phone) or crud.get_or_create_client(phone)
        cid = row["id"]
        if plan in ("1x", "2x", "3x"):
            _save_plan(cid, plan)
        if day and mon:
            try:
                crud.update_client_dob(cid, int(day), int(mon))
            except Exception:
                logging.exception("DOB update failed")
        if medical and medical != "-":
            crud.update_client_medical(cid, medical, append=False)

        _set_state(wa, flow=None, await=None, cid=None)
        st["buffer"].clear(); st["book"].clear()
        send_whatsapp_text(wa, "✅ New client saved.")
        return _root_menu(wa)

    # default: restart wizard
    return _start_new(wa, st)

def _capture_free_text(wa: str, st: dict, raw: str):
    """Capture free-text for the current awaited field (NEW/UPDATE/NOTIFY)."""
    field = st.get("await")
    txt = (raw or "").strip()

    # ── NOTIFY: custom broadcast
    if st.get("flow") == "NOTIFY" and field == "CUSTOM_BROADCAST":
        if len(txt) < 5:
            return _ask_free_text(wa, "Custom Broadcast", "Message is too short — try again.", back_id="ADMIN_INTENT_NOTIFY")
        count = _broadcast_to_all(txt)
        _set_state(wa, await=None)
        return send_whatsapp_text(wa, f"✅ Broadcast sent to {count} clients.")

    # ── NEW flow capture
    if st.get("flow") == "NEW":
        buf = st.setdefault("buffer", {})
        if field == "NAME":
            if len(txt) < 2:
                return _ask_free_text(wa, "New Client", "Name seems too short — please reply with full name.", "ADMIN_INTENT_NEW")
            buf["NAME"] = txt.title()[:120]
            _set_state(wa, await="PHONE")
            return _ask_free_text(wa, "New Client", "Reply with the client's phone (0XXXXXXXXX, +27…, or 27…).", "ADMIN_INTENT_NEW")

        if field == "PHONE":
            norm = normalize_wa(txt)
            if not norm.startswith("+27"):
                return _ask_free_text(wa, "New Client", "Please send a valid SA phone (0…, 27…, or +27…).", "ADMIN_INTENT_NEW")
            buf["PHONE"] = norm
            _set_state(wa, await="PLAN")
            return _ask_free_text(wa, "New Client", "Reply with plan: 1x, 2x, or 3x.", "ADMIN_INTENT_NEW")

        if field == "PLAN":
            low = txt.lower()
            if low not in ("1x", "2x", "3x"):
                return _ask_free_text(wa, "New Client", "Please reply with 1x, 2x, or 3x.", "ADMIN_INTENT_NEW")
            buf["PLAN"] = low
            _set_state(wa, await="DOB")
            return _ask_free_text(wa, "New Client", "Reply DOB as DD MON (e.g., 21 MAY).", "ADMIN_INTENT_NEW")

        if field == "DOB":
            m = re.fullmatch(r"\s*(\d{1,2})\s+([A-Za-z]{3,})\s*", txt)
            if not m:
                return _ask_free_text(wa, "New Client", "Format DD MON (e.g., 21 MAY).", "ADMIN_INTENT_NEW")
            day_s, mon_s = m.group(1), m.group(2)
            mon_i = _month_to_int(mon_s)
            if mon_i is None:
                return _ask_free_text(wa, "New Client", "Month must be JAN, FEB, …", "ADMIN_INTENT_NEW")
            buf["DOB_DAY"], buf["DOB_MON"] = day_s, mon_i
            _set_state(wa, await="MEDICAL")
            return _ask_free_text(wa, "New Client", "Medical notes (optional). Reply '-' to skip.", "ADMIN_INTENT_NEW")

        if field == "MEDICAL":
            buf["MEDICAL"] = txt[:500]
            # finalize by calling the internal next-step
            return handle_admin_action(wa, "ADMIN_NEW_NEXT")

    # ── UPDATE flow capture
    if st.get("flow") == "UPDATE" and st.get("cid"):
        cid = st["cid"]
        if field == "NAME":
            if len(txt) < 2:
                return _ask_free_text(wa, "Edit Name", "Name seems too short — please reply with full name.")
            _save_name(cid, txt.title()[:120])
            _set_state(wa, await=None)
            send_whatsapp_text(wa, "✅ Name updated.")
            return _update_menu(wa, cid)

        if field == "PLAN":
            low = txt.lower()
            if low not in ("1x", "2x", "3x"):
                return _ask_free_text(wa, "Edit Plan", "Please reply with 1x, 2x, or 3x.")
            _save_plan(cid, low)
            _set_state(wa, await=None)
            send_whatsapp_text(wa, "✅ Plan updated.")
            return _update_menu(wa, cid)

        if field == "MEDICAL":
            crud.update_client_medical(cid, txt[:500], append=False)
            _set_state(wa, await=None)
            send_whatsapp_text(wa, "✅ Medical notes updated.")
            return _update_menu(wa, cid)

        if field == "CREDITS":
            m = re.fullmatch(r"\s*([+-]?\d+)\s*", txt)
            if not m:
                return _ask_free_text(wa, "Adjust Credits", "Reply with +N or -N (e.g., +1, -2).")
            delta = int(m.group(1))
            _save_credits_delta(cid, delta)
            _set_state(wa, await=None)
            send_whatsapp_text(wa, f"✅ Credits adjusted by {delta}.")
            return _update_menu(wa, cid)

        if field == "DOB":
            m = re.fullmatch(r"\s*(\d{1,2})\s+([A-Za-z]{3,})\s*", txt)
            if not m:
                return _ask_free_text(wa, "Edit DOB", "Format DD MON (e.g., 21 MAY).")
            day_s, mon_s = m.group(1), m.group(2)
            mon_i = _month_to_int(mon_s)
            if mon_i is None:
                return _ask_free_text(wa, "Edit DOB", "Month must be JAN, FEB, …")
            crud.update_client_dob(cid, int(day_s), int(mon_i))
            _set_state(wa, await=None)
            send_whatsapp_text(wa, "✅ DOB updated.")
            return _update_menu(wa, cid)

    # default: clear await and return to root
    _set_state(wa, await=None)
    return _root_menu(wa)

# ──────────────────────────────────────────────────────────────────────────────
# Utilities
# ──────────────────────────────────────────────────────────────────────────────
def _month_to_int(mon: str) -> int | None:
    mon = mon.strip().lower()
    table = {
        "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
        "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
        "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10,
        "nov": 11, "november": 11, "dec": 12, "december": 12
    }
    return table.get(mon)
