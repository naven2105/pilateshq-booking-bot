# app/admin.py
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
# Admin auth
# ──────────────────────────────────────────────────────────────────────────────
ADMIN_WA_LIST = [n.strip() for n in os.getenv("ADMIN_WA_LIST", "").split(",") if n.strip()]
NADINE_WA = os.getenv("NADINE_WA", "").strip()

def _is_admin(sender: str) -> bool:
    wa = normalize_wa(sender)
    allow = set(normalize_wa(x) for x in ADMIN_WA_LIST if x)
    if NADINE_WA:
        allow.add(normalize_wa(NADINE_WA))
    ok = wa in allow
    logging.debug(f"[ADMIN AUTH] sender={wa} allow={sorted(list(allow))} ok={ok}")
    return ok

# ──────────────────────────────────────────────────────────────────────────────
# Minimal state (per admin WA)
# ──────────────────────────────────────────────────────────────────────────────
# ADMIN_STATE["+27..."] = {
#   "flow": "NEW" | "UPDATE" | "CANCEL" | "VIEW" | "BOOK" | "BROADCAST" | "OFFSICK",
#   "await": "NAME" | "PHONE" | "DOB" | "PLAN" | "MEDICAL" | "BROADCAST_TEXT" | None,
#   "cid": int | None,
#   "buffer": dict,
#   "book": dict
# }
ADMIN_STATE = {}

# ──────────────────────────────────────────────────────────────────────────────
# UI helpers
# ──────────────────────────────────────────────────────────────────────────────
def _root_menu(to: str):
    return send_whatsapp_list(
        to, "Admin", "Type a single word or tap:", "ADMIN_ROOT",
        [
            {"id": "ADMIN_INTENT_NEW",       "title": "➕ New"},
            {"id": "ADMIN_INTENT_UPDATE",    "title": "✏️ Update"},
            {"id": "ADMIN_INTENT_CANCEL",    "title": "❌ Cancel"},
            {"id": "ADMIN_INTENT_VIEW",      "title": "👁️ View"},
            {"id": "ADMIN_INTENT_BOOK",      "title": "📅 Book"},
            {"id": "ADMIN_INTENT_BROADCAST", "title": "📣 Broadcast"},
            {"id": "ADMIN_INTENT_OFFSICK",   "title": "🤒 Off Sick"},
        ],
    )

def _client_picker(to: str, title="Clients", q: str | None = None):
    rows = []
    if q:
        matches = crud.find_clients_by_name(q, limit=10)
    else:
        matches = crud.list_clients(limit=10)
    for c in matches:
        rows.append({
            "id": f"ADMIN_PICK_CLIENT_{c['id']}",
            "title": (c["name"] or "(no name)")[:24],
            "description": f"{c['wa_number']} • {c.get('credits',0)} cr"
        })
    body = "Pick a client:" + (f' (search="{q}")' if q else "")
    return send_whatsapp_list(to, title, body, "ADMIN_CLIENTS", rows or [{"id": "ADMIN_ROOT", "title": "⬅️ Back"}])

def _show_profile(to: str, cid: int):
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

def _ask_free_text(to: str, header: str, prompt: str, back_id="ADMIN_ROOT"):
    return send_whatsapp_list(
        to, header, prompt, "ADMIN_BACK",
        [{"id": back_id, "title": "⬅️ Back"}]
    )

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
# Helpers: state set/get
# ──────────────────────────────────────────────────────────────────────────────
def _get_state(wa: str):
    st = ADMIN_STATE.get(wa)
    if not st:
        st = {"flow": None, "await": None, "cid": None, "buffer": {}, "book": {}}
        ADMIN_STATE[wa] = st
    return st

def _set_state(wa: str, *, flow=None, await_field=None, cid=None, buffer=None, book=None):
    st = _get_state(wa)
    if flow is not None: st["flow"] = flow
    if await_field is not None: st["await"] = await_field
    if cid is not None: st["cid"] = cid
    if buffer is not None: st["buffer"] = buffer
    if book is not None: st["book"] = book
    ADMIN_STATE[wa] = st
    return st

def _reset_state(wa: str):
    ADMIN_STATE[wa] = {"flow": None, "await": None, "cid": None, "buffer": {}, "book": {}}

# ──────────────────────────────────────────────────────────────────────────────
# Entry
# ──────────────────────────────────────────────────────────────────────────────
def handle_admin_action(sender: str, text: str):
    if not _is_admin(sender):
        return send_whatsapp_text(sender, "⛔ Only Nadine (admin) can perform admin functions.")

    wa = normalize_wa(sender)
    state = _get_state(wa)

    raw = (text or "").strip()
    up = raw.upper()
    logging.info(f"[ADMIN CMD] '{raw}' (flow={state['flow']} await={state['await']} cid={state['cid']})")

    # ── Intent buttons
    if up == "ADMIN_INTENT_NEW":
        _set_state(wa, flow="NEW", await_field=None, cid=None, buffer={}, book={})
        return _start_new(wa, state)

    if up == "ADMIN_INTENT_UPDATE":
        _set_state(wa, flow="UPDATE", await_field=None)
        return _client_picker(wa, "Update: pick client")

    if up == "ADMIN_INTENT_CANCEL":
        _set_state(wa, flow="CANCEL", await_field=None)
        return _client_picker(wa, "Cancel: pick client")

    if up == "ADMIN_INTENT_VIEW":
        _set_state(wa, flow="VIEW", await_field=None)
        return _client_picker(wa, "View: pick client")

    if up == "ADMIN_INTENT_BOOK":
        _set_state(wa, flow="BOOK", await_field=None)
        return _client_picker(wa, "Book: pick client")

    if up == "ADMIN_INTENT_BROADCAST":
        _set_state(wa, flow="BROADCAST", await_field="BROADCAST_TEXT")
        return _ask_free_text(wa, "Broadcast", "Reply with the message to send to all clients.", "ADMIN_ROOT")

    if up == "ADMIN_INTENT_OFFSICK":
        _set_state(wa, flow="OFFSICK", await_field=None)
        today = date.today().isoformat()
        body = f"Cancel all sessions from *{today}* onwards?\nThis sets status to 'cancelled' for all future sessions."
        return send_whatsapp_buttons(wa, body, [
            {"id": "ADMIN_OFFSICK_CONFIRM", "title": "Confirm"},
            {"id": "ADMIN_ROOT",            "title": "Cancel"},
        ])

    # ── Off Sick confirmation
    if up == "ADMIN_OFFSICK_CONFIRM":
        affected = crud.cancel_sessions_from(date.today())
        send_whatsapp_text(wa, f"✅ Cancelled {affected} future session(s).")
        # Offer immediate broadcast with a suggested message
        default_msg = (
            "Hi everyone — Nadine here. I’m unfortunately off sick and today’s upcoming classes are cancelled. "
            "I’ll message soon with make-up options. Thank you for understanding. 🙏"
        )
        _set_state(wa, flow="BROADCAST", await_field="BROADCAST_TEXT", buffer={"SUGGESTED_BROADCAST": default_msg})
        return _ask_free_text(wa, "Broadcast (optional)", f"Edit and send this message to all clients:\n\n{default_msg}\n\nReply with your final text.", "ADMIN_ROOT")

    # ── Broadcast capture/confirm
    if state.get("flow") == "BROADCAST" and state.get("await") == "BROADCAST_TEXT" and raw:
        msg = raw.strip()
        nums = crud.list_all_client_numbers()
        sent = 0
        for wa_num in nums:
            try:
                send_whatsapp_text(wa_num, msg)
                sent += 1
            except Exception:
                logging.exception(f"[BROADCAST] failed to send to {wa_num}")
        _reset_state(wa)
        return send_whatsapp_text(wa, f"📣 Broadcast sent to {sent} client(s).")

    # ── Client selection
    if up.startswith("ADMIN_PICK_CLIENT_"):
        try:
            cid = int(up.replace("ADMIN_PICK_CLIENT_", ""))
        except ValueError:
            return send_whatsapp_text(wa, "Invalid selection.")
        _set_state(wa, cid=cid)
        flow = state["flow"]
        if flow == "VIEW":
            return _show_profile(wa, cid)
        if flow == "UPDATE":
            return _update_menu(wa, cid)
        if flow == "CANCEL":
            # Placeholder: depends on your booking cancel helper
            return send_whatsapp_text(wa, "Use the update menu to manage client or a specific cancel helper (not wired here).")
        if flow == "BOOK":
            return _book_type_menu(wa)
        return _root_menu(wa)

    # ── UPDATE: edit selections
    if up in ("ADMIN_EDIT_NAME", "ADMIN_EDIT_DOB", "ADMIN_EDIT_PLAN", "ADMIN_EDIT_MEDICAL", "ADMIN_EDIT_CREDITS"):
        if not state["cid"]:
            return _client_picker(wa, "Update: pick client")
        if up == "ADMIN_EDIT_NAME":
            _set_state(wa, await_field="NAME")
            return _ask_free_text(wa, "Edit Name", "Reply with the client's full name.")
        if up == "ADMIN_EDIT_DOB":
            _set_state(wa, await_field="DOB")
            return _ask_free_text(wa, "Edit DOB", "Reply as DD MON (e.g., 21 MAY).")
        if up == "ADMIN_EDIT_PLAN":
            _set_state(wa, await_field="PLAN")
            return _ask_free_text(wa, "Edit Plan", "Reply with: 1x, 2x, or 3x.")
        if up == "ADMIN_EDIT_MEDICAL":
            _set_state(wa, await_field="MEDICAL")
            return _ask_free_text(wa, "Edit Medical Notes", "Reply with the medical note (replaces existing).")
        if up == "ADMIN_EDIT_CREDITS":
            _set_state(wa, await_field="CREDITS")
            return _ask_free_text(wa, "Adjust Credits", "Reply with +N or -N (e.g., +1, -2).")
        return _update_menu(wa, state["cid"])

    if up == "ADMIN_DONE":
        _reset_state(wa)
        return _root_menu(wa)

    # ── BOOK: type/mode/slot selection
    if up.startswith("ADMIN_BOOK_TYPE_"):
        t = up.replace("ADMIN_BOOK_TYPE_", "").lower()
        st = _get_state(wa)
        st["book"]["type"] = t
        return _book_mode_menu(wa)

    if up.startswith("ADMIN_BOOK_MODE_"):
        m = up.replace("ADMIN_BOOK_MODE_", "").lower()
        st = _get_state(wa)
        st["book"]["mode"] = m
        return _book_slot_menu(wa)

    if up.startswith("ADMIN_BOOK_SLOT_"):
        try:
            slot_id = int(up.replace("ADMIN_BOOK_SLOT_", ""))
        except ValueError:
            return send_whatsapp_text(wa, "Invalid slot.")
        st = _get_state(wa)
        st["book"]["slot_id"] = slot_id
        prof = crud.get_client_profile(st["cid"]) if st["cid"] else None
        nm = prof["name"] if prof else "client"
        body = f"Confirm booking for {nm}\n• Type: {st['book'].get('type')}\n• Mode: {st['book'].get('mode')}\n• Slot ID: {slot_id}"
        return send_whatsapp_buttons(wa, body, [
            {"id": f"ADMIN_BOOK_CONFIRM", "title": "Confirm"},
            {"id": "ADMIN_INTENT_BOOK",   "title": "Back"},
        ])

    if up == "ADMIN_BOOK_CONFIRM":
        st = _get_state(wa)
        if not (st.get("cid") and st.get("book", {}).get("slot_id")):
            return send_whatsapp_text(wa, "Missing selection.")
        prof = crud.get_client_profile(st["cid"])
        ok = booking.admin_reserve(prof["wa_number"], st["book"]["slot_id"], seats=1)
        if ok:
            send_whatsapp_text(wa, "✅ Booked.")
        else:
            send_whatsapp_text(wa, "⚠️ Could not book (full?).")
        st["book"] = {}
        return _update_menu(wa, st["cid"])

    # ── NEW flow: next step trigger
    if up == "ADMIN_NEW_NEXT":
        return _new_next(wa, state)

    # ── Free text routing (NEW/UPDATE/BROADCAST)
    if state.get("await"):
        return _capture_free_text(wa, state, raw)

    # ── Single-word text intents
    low = raw.lower()
    if low in ("new", "update", "cancel", "view", "book", "broadcast", "off sick", "offsick", "off-sick"):
        mapping = {
            "new": "ADMIN_INTENT_NEW",
            "update": "ADMIN_INTENT_UPDATE",
            "cancel": "ADMIN_INTENT_CANCEL",
            "view": "ADMIN_INTENT_VIEW",
            "book": "ADMIN_INTENT_BOOK",
            "broadcast": "ADMIN_INTENT_BROADCAST",
            "off sick": "ADMIN_INTENT_OFFSICK",
            "offsick": "ADMIN_INTENT_OFFSICK",
            "off-sick": "ADMIN_INTENT_OFFSICK",
        }
        return handle_admin_action(wa, mapping[low])

    # ── NLP fallbacks (unchanged)
    nlp = parse_admin_client_command(raw) or parse_admin_command(raw)
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
            return handle_admin_action(wa, "ADMIN_INTENT_OFFSICK")
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
            return send_whatsapp_text(wa, "✅ Recurring booking stub (wire your weekly finder).")

    # Default
    return _root_menu(wa)

# ──────────────────────────────────────────────────────────────────────────────
# NEW CLIENT WIZARD
# ──────────────────────────────────────────────────────────────────────────────
def _start_new(wa: str, state: dict):
    _set_state(wa, await_field="NAME", buffer={}, cid=None)
    return _ask_free_text(wa, "New Client", "Reply with the client's full name.", "ADMIN_INTENT_NEW")

def _new_next(wa: str, state: dict):
    step = state.get("await")
    buf = state.get("buffer", {})
    if step == "NAME":
        _set_state(wa, await_field="PHONE")
        return _ask_free_text(wa, "New Client", "Reply with the client's phone (0XXXXXXXXX, +27…, or 27…).", "ADMIN_INTENT_NEW")
    if step == "PHONE":
        _set_state(wa, await_field="PLAN")
        return _ask_free_text(wa, "New Client", "Reply with plan: 1x, 2x, or 3x.", "ADMIN_INTENT_NEW")
    if step == "PLAN":
        _set_state(wa, await_field="DOB")
        return _ask_free_text(wa, "New Client", "Reply DOB as DD MON (e.g., 21 MAY).", "ADMIN_INTENT_NEW")
    if step == "DOB":
        _set_state(wa, await_field="MEDICAL")
        return _ask_free_text(wa, "New Client", "Medical notes (optional). Reply '-' to skip.", "ADMIN_INTENT_NEW")
    if step == "MEDICAL":
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
        _reset_state(wa)
        send_whatsapp_text(wa, "✅ New client saved.")
        return _root_menu(wa)
    return _start_new(wa, state)

def _capture_free_text(wa: str, state: dict, raw: str):
    field = state.get("await")
    txt = (raw or "").strip()

    # NEW flow
    if state.get("flow") == "NEW":
        buf = state.setdefault("buffer", {})
        if field == "NAME":
            if len(txt) < 2:
                return _ask_free_text(wa, "New Client", "Name seems too short — please reply with full name.", "ADMIN_INTENT_NEW")
            buf["NAME"] = txt.title()[:120]
            _set_state(wa, await_field="PHONE")
            return _ask_free_text(wa, "New Client", "Reply with the client's phone (0XXXXXXXXX, +27…, or 27…).", "ADMIN_INTENT_NEW")

        if field == "PHONE":
            norm = normalize_wa(txt)
            if not norm.startswith("+27"):
                return _ask_free_text(wa, "New Client", "Please send a valid SA phone (0…, 27…, or +27…).", "ADMIN_INTENT_NEW")
            buf["PHONE"] = norm
            _set_state(wa, await_field="PLAN")
            return _ask_free_text(wa, "New Client", "Reply with plan: 1x, 2x, or 3x.", "ADMIN_INTENT_NEW")

        if field == "PLAN":
            low = txt.lower()
            if low not in ("1x", "2x", "3x"):
                return _ask_free_text(wa, "New Client", "Please reply with 1x, 2x, or 3x.", "ADMIN_INTENT_NEW")
            buf["PLAN"] = low
            _set_state(wa, await_field="DOB")
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
            _set_state(wa, await_field="MEDICAL")
            return _ask_free_text(wa, "New Client", "Medical notes (optional). Reply '-' to skip.", "ADMIN_INTENT_NEW")

        if field == "MEDICAL":
            buf["MEDICAL"] = txt[:500]
            _set_state(wa, await_field="MEDICAL")  # guard
            return handle_admin_action(wa, "ADMIN_NEW_NEXT")

    # UPDATE flow
    if state.get("flow") == "UPDATE" and state.get("cid"):
        cid = state["cid"]
        if field == "NAME":
            if len(txt) < 2:
                return _ask_free_text(wa, "Edit Name", "Name seems too short — please reply with full name.")
            _save_name(cid, txt.title()[:120])
            _set_state(wa, await_field=None)
            send_whatsapp_text(wa, "✅ Name updated.")
            return _update_menu(wa, cid)

        if field == "PLAN":
            low = txt.lower()
            if low not in ("1x", "2x", "3x"):
                return _ask_free_text(wa, "Edit Plan", "Please reply with 1x, 2x, or 3x.")
            _save_plan(cid, low)
            _set_state(wa, await_field=None)
            send_whatsapp_text(wa, "✅ Plan updated.")
            return _update_menu(wa, cid)

        if field == "MEDICAL":
            crud.update_client_medical(cid, txt[:500], append=False)
            _set_state(wa, await_field=None)
            send_whatsapp_text(wa, "✅ Medical notes updated.")
            return _update_menu(wa, cid)

        if field == "CREDITS":
            m = re.fullmatch(r"\s*([+-]?\d+)\s*", txt)
            if not m:
                return _ask_free_text(wa, "Adjust Credits", "Reply with +N or -N (e.g., +1, -2).")
            delta = int(m.group(1))
            _save_credits_delta(cid, delta)
            _set_state(wa, await_field=None)
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
            _set_state(wa, await_field=None)
            send_whatsapp_text(wa, "✅ DOB updated.")
            return _update_menu(wa, cid)

    # BROADCAST flow: handled above when we detect await == BROADCAST_TEXT

    # default
    _set_state(wa, await_field=None)
    return _root_menu(wa)

# ──────────────────────────────────────────────────────────────────────────────
# Utilities (month parsing)
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
