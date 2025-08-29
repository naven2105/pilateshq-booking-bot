# app/admin.py
import os
import re
import logging
from datetime import date, datetime, timedelta
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
# NEW FLOW: single-word intents + small state machine
# Intents: new, update, cancel, view, book
# ──────────────────────────────────────────────────────────────────────────────
INTENTS = {"NEW", "UPDATE", "CANCEL", "VIEW", "BOOK"}

# Minimal in-memory per-admin state. Keyed by the admin’s WA number.
# Example state:
# ADMIN_STATE["+27..."] = {
#   "flow": "NEW" | "UPDATE" | "CANCEL" | "VIEW" | "BOOK",
#   "await": "NAME" | "PHONE" | "DOB" | "PLAN" | "MEDICAL" | None,
#   "cid": 123,           # selected client id (for update/cancel/view/book)
#   "buffer": {...},      # transient answers in the wizard
#   "book": { "type": "single/duo/group", "mode": "one/ongoing", "slot_id": 1 }
# }
ADMIN_STATE = {}

# Seats mapping by booking type
SEATS_BY_TYPE = {"single": 1, "duo": 2, "group": 1}

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def _root_menu(to: str):
    return send_whatsapp_list(
        to, "Admin", "Type a single word to start or tap:", "ADMIN_ROOT",
        [
            {"id": "ADMIN_INTENT_NEW",    "title": "➕ New"},
            {"id": "ADMIN_INTENT_UPDATE", "title": "✏️ Update"},
            {"id": "ADMIN_INTENT_CANCEL", "title": "❌ Cancel"},
            {"id": "ADMIN_INTENT_VIEW",   "title": "👁️ View"},
            {"id": "ADMIN_INTENT_BOOK",   "title": "📅 Book"},
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

def _cancel_menu(to: str, cid: int):
    return send_whatsapp_list(
        to, "Cancel / Attendance", "Choose an action:", "ADMIN_CANCEL",
        [
            {"id": "ADMIN_CANCEL_NEXT", "title": "❌ Cancel Next"},
            {"id": "ADMIN_NO_SHOW",     "title": "🚫 No-show Today"},
            {"id": "ADMIN_DONE",        "title": "✅ Done"},
        ],
    )

def _ask_free_text(to: str, header: str, prompt: str, back_id="ADMIN_INTENT_UPDATE"):
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

def _get_session_row(session_id: int):
    with get_session() as s:
        r = s.execute(text("""
            SELECT id, session_date, start_time, capacity, booked_count, status
            FROM sessions WHERE id = :sid
        """), {"sid": session_id}).mappings().first()
        return dict(r) if r else None

def _find_session_by_date_time_safe(d: date, hhmm: str):
    # Try to use a helper in crud if present; else inline a simple match by date+time.
    fn = getattr(crud, "find_session_by_date_time", None)
    if fn:
        return fn(d, hhmm)
    with get_session() as s:
        r = s.execute(text("""
            SELECT id, session_date, start_time, capacity, booked_count, status
            FROM sessions
            WHERE session_date = :d AND start_time = :t
            LIMIT 1
        """), {"d": d, "t": hhmm}).mappings().first()
        return dict(r) if r else None

def _iter_weekly_dates(start: date, weekday: int, count: int):
    """Yield `count` dates starting from the next `weekday` on/after start."""
    # weekday: Monday=0..Sunday=6
    days_ahead = (weekday - start.weekday()) % 7
    first = start + timedelta(days=days_ahead or 7)  # always next occurrence (not same day)
    for i in range(count):
        yield first + timedelta(days=7 * i)

# ──────────────────────────────────────────────────────────────────────────────
# Entry
# ──────────────────────────────────────────────────────────────────────────────
def handle_admin_action(sender: str, text: str):
    if not _is_admin(sender):
        return send_whatsapp_text(sender, "⛔ Only Nadine (admin) can perform admin functions.")

    wa = normalize_wa(sender)
    state = ADMIN_STATE.get(wa) or {"flow": None, "await": None, "cid": None, "buffer": {}, "book": {}}
    ADMIN_STATE[wa] = state

    raw = (text or "").strip()
    up = raw.upper()
    logging.info(f"[ADMIN CMD] '{raw}' (flow={state['flow']} await={state['await']} cid={state['cid']})")

    # ── Handle intent shortcuts (interactive buttons)
    if up == "ADMIN_INTENT_NEW":     state.update({"flow": "NEW",    "await": None, "cid": None, "buffer": {}, "book": {}});  return _start_new(wa, state)
    if up == "ADMIN_INTENT_UPDATE":  state.update({"flow": "UPDATE", "await": None}); return _client_picker(wa, "Update: pick client")
    if up == "ADMIN_INTENT_CANCEL":  state.update({"flow": "CANCEL", "await": None}); return _client_picker(wa, "Cancel: pick client")
    if up == "ADMIN_INTENT_VIEW":    state.update({"flow": "VIEW",   "await": None}); return _client_picker(wa, "View: pick client")
    if up == "ADMIN_INTENT_BOOK":    state.update({"flow": "BOOK",   "await": None}); return _client_picker(wa, "Book: pick client")

    # ── Client selection from list
    if up.startswith("ADMIN_PICK_CLIENT_"):
        try:
            cid = int(up.replace("ADMIN_PICK_CLIENT_", ""))
        except ValueError:
            return send_whatsapp_text(wa, "Invalid selection.")
        state["cid"] = cid
        if state["flow"] == "VIEW":
            return _show_profile(wa, cid)
        if state["flow"] == "UPDATE":
            return _update_menu(wa, cid)
        if state["flow"] == "CANCEL":
            return _cancel_menu(wa, cid)
        if state["flow"] == "BOOK":
            return _book_type_menu(wa)
        return _root_menu(wa)

    # ── CANCEL actions
    if up in ("ADMIN_CANCEL_NEXT","ADMIN_NO_SHOW"):
        if not state["cid"]:
            return _client_picker(wa, "Cancel: pick client")
        cid = state["cid"]
        if up == "ADMIN_CANCEL_NEXT":
            ok = getattr(crud, "cancel_next_booking_for_client", lambda *_: False)(cid)
            return send_whatsapp_text(wa, "✅ Next session cancelled." if ok else "⚠️ No upcoming booking found.")
        if up == "ADMIN_NO_SHOW":
            ok = getattr(crud, "mark_no_show_today", lambda *_: False)(cid)
            return send_whatsapp_text(wa, "✅ No-show recorded." if ok else "⚠️ No booking found today.")

    # ── UPDATE: edit selections
    if up in ("ADMIN_EDIT_NAME", "ADMIN_EDIT_DOB", "ADMIN_EDIT_PLAN", "ADMIN_EDIT_MEDICAL", "ADMIN_EDIT_CREDITS"):
        if not state["cid"]:
            return _client_picker(wa, "Update: pick client")
        if up == "ADMIN_EDIT_NAME":
            state["await"] = "NAME"
            return _ask_free_text(wa, "Edit Name", "Reply with the client's full name.")
        if up == "ADMIN_EDIT_DOB":
            state["await"] = "DOB"
            return _ask_free_text(wa, "Edit DOB", "Reply as DD MON (e.g., 21 MAY).")
        if up == "ADMIN_EDIT_PLAN":
            state["await"] = "PLAN"
            return _ask_free_text(wa, "Edit Plan", "Reply with: 1x, 2x, or 3x.")
        if up == "ADMIN_EDIT_MEDICAL":
            state["await"] = "MEDICAL"
            return _ask_free_text(wa, "Edit Medical Notes", "Reply with the medical note (replaces existing).")
        if up == "ADMIN_EDIT_CREDITS":
            state["await"] = "CREDITS"
            return _ask_free_text(wa, "Adjust Credits", "Reply with +N or -N (e.g., +1, -2).")
        # fallthrough returns to update menu
        return _update_menu(wa, state["cid"])

    if up == "ADMIN_DONE":
        state.update({"flow": None, "await": None, "cid": None, "buffer": {}, "book": {}})
        return _root_menu(wa)

    # ── BOOK: type/mode/slot selection
    if up.startswith("ADMIN_BOOK_TYPE_"):
        t = up.replace("ADMIN_BOOK_TYPE_", "").lower()
        state["book"]["type"] = t
        return _book_mode_menu(wa)

    if up.startswith("ADMIN_BOOK_MODE_"):
        m = up.replace("ADMIN_BOOK_MODE_", "").lower()
        state["book"]["mode"] = m
        return _book_slot_menu(wa)

    if up.startswith("ADMIN_BOOK_SLOT_"):
        try:
            slot_id = int(up.replace("ADMIN_BOOK_SLOT_", ""))
        except ValueError:
            return send_whatsapp_text(wa, "Invalid slot.")
        state["book"]["slot_id"] = slot_id
        prof = crud.get_client_profile(state["cid"]) if state["cid"] else None
        nm = prof["name"] if prof else "client"
        body = f"Confirm booking for {nm}\n• Type: {state['book'].get('type')}\n• Mode: {state['book'].get('mode')}\n• Slot ID: {slot_id}"
        return send_whatsapp_buttons(wa, body, [
            {"id": f"ADMIN_BOOK_CONFIRM", "title": "Confirm"},
            {"id": "ADMIN_INTENT_BOOK", "title": "Back"},
        ])

    if up == "ADMIN_BOOK_CONFIRM":
        if not (state.get("cid") and state.get("book", {}).get("slot_id")):
            return send_whatsapp_text(wa, "Missing selection.")
        prof = crud.get_client_profile(state["cid"])
        seats = SEATS_BY_TYPE.get(state["book"].get("type","single"), 1)

        # Reserve selected slot
        ok1 = booking.admin_reserve(prof["wa_number"], state["book"]["slot_id"], seats=seats)

        # If ongoing, try to pre-book the next 3 weeks (configurable)
        if ok1 and state["book"].get("mode") == "ongoing":
            base = _get_session_row(state["book"]["slot_id"])
            if base:
                base_date = base["session_date"] if isinstance(base["session_date"], date) else date.fromisoformat(str(base["session_date"]))
                start_time = base["start_time"]
                booked_more = 0
                for i in range(1, 4):  # next 3 weeks
                    d = base_date + timedelta(days=7*i)
                    nxt = _find_session_by_date_time_safe(d, start_time)
                    if not nxt:
                        continue
                    if booking.admin_reserve(prof["wa_number"], nxt["id"], seats=seats):
                        booked_more += 1
                send_whatsapp_text(wa, f"✅ Booked. Ongoing: +{booked_more} future weeks.")
            else:
                send_whatsapp_text(wa, "✅ Booked. (Could not prefill ongoing; slot lookup failed.)")
        else:
            send_whatsapp_text(wa, "✅ Booked." if ok1 else "⚠️ Could not book (full?).")

        # reset booking state but keep client selected for quick follow-ups
        state["book"] = {}
        return _update_menu(wa, state["cid"])

    # ── NEW: wizard (interactive entry point)
    if up == "ADMIN_NEW_NEXT":
        # step through in fixed order: NAME -> PHONE -> PLAN -> DOB -> MEDICAL -> CONFIRM
        return _new_next(wa, state)

    # ── Text fallback: treat as free text for whichever field we await
    if state["await"]:
        return _capture_free_text(wa, state, raw)

    # ── If a single-word admin intent is typed, start those flows
    low = raw.lower()
    if low in ("new", "update", "cancel", "view", "book"):
        # Map to the corresponding interactive IDs to reuse logic
        return handle_admin_action(wa, f"ADMIN_INTENT_{low.upper()}")

    # Optional: inline search when inside a flow without awaiting a field
    if state["flow"] in {"UPDATE", "CANCEL", "VIEW", "BOOK"} and raw and raw.lower() not in {x.lower() for x in INTENTS}:
        return _client_picker(wa, f"{state['flow'].title()}: search", raw)

    # Try NLP fallbacks if not in the middle of a wizard and no intent matched
    if not state.get("await"):
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
                # Placeholder: wire a dedicated helper if you track excused absences
                return send_whatsapp_text(wa, "✅ Noted off sick (stub).")
            if intent == "no_show_today":
                match = crud.find_clients_by_name(nlp["name"], limit=1)
                if not match: return send_whatsapp_text(wa, "⚠️ No client found.")
                ok = getattr(crud, "mark_no_show_today", lambda *_: False)(match[0]["id"])
                return send_whatsapp_text(wa, "✅ No-show recorded." if ok else "⚠️ No booking found today.")
            if intent == "book_single":
                # find session by date+time and reserve
                sess = _find_session_by_date_time_safe(date.fromisoformat(nlp["date"]), nlp["time"])
                if not sess: return send_whatsapp_text(wa, "⚠️ No matching session found.")
                match = crud.find_clients_by_name(nlp["name"], limit=1)
                if not match: return send_whatsapp_text(wa, "⚠️ No client found.")
                prof = crud.get_client_profile(match[0]["id"])
                seats = SEATS_BY_TYPE.get("single", 1)
                ok = booking.admin_reserve(prof["wa_number"], sess["id"], seats=seats)
                return send_whatsapp_text(wa, "✅ Booked." if ok else "⚠️ Could not book (full?).")
            if intent == "book_recurring":
                # Recurring booking: next N weeks at weekday+time
                match = crud.find_clients_by_name(nlp["name"], limit=1)
                if not match: return send_whatsapp_text(wa, "⚠️ No client found.")
                prof = crud.get_client_profile(match[0]["id"])
                weekday = int(nlp["weekday"])
                hhmm = nlp["time"]
                weeks = max(1, int(nlp.get("weeks", 4)))
                today = date.today()
                booked = 0
                for d in _iter_weekly_dates(today, weekday, weeks):
                    sess = _find_session_by_date_time_safe(d, hhmm)
                    if not sess:
                        continue
                    if booking.admin_reserve(prof["wa_number"], sess["id"], seats=SEATS_BY_TYPE.get("single", 1)):
                        booked += 1
                return send_whatsapp_text(wa, f"✅ Recurring booked {booked}/{weeks} weeks.")

    # Otherwise, show the new root
    return _root_menu(wa)

# ──────────────────────────────────────────────────────────────────────────────
# NEW CLIENT WIZARD
# ──────────────────────────────────────────────────────────────────────────────
def _start_new(wa: str, state: dict):
    state.update({"await": "NAME", "buffer": {}, "cid": None})
    return _ask_free_text(wa, "New Client", "Reply with the client's full name.", "ADMIN_INTENT_NEW")

def _new_next(wa: str, state: dict):
    step = state.get("await")
    buf = state.get("buffer", {})
    if step == "NAME":
        state["await"] = "PHONE"
        return _ask_free_text(wa, "New Client", "Reply with the client's phone (0XXXXXXXXX, +27…, or 27…).", "ADMIN_INTENT_NEW")
    if step == "PHONE":
        state["await"] = "PLAN"
        return _ask_free_text(wa, "New Client", "Reply with plan: 1x, 2x, or 3x.", "ADMIN_INTENT_NEW")
    if step == "PLAN":
        state["await"] = "DOB"
        return _ask_free_text(wa, "New Client", "Reply DOB as DD MON (e.g., 21 MAY).", "ADMIN_INTENT_NEW")
    if step == "DOB":
        state["await"] = "MEDICAL"
        return _ask_free_text(wa, "New Client", "Medical notes (optional). Reply '-' to skip.", "ADMIN_INTENT_NEW")
    if step == "MEDICAL":
        # Persist all fields now
        name = (buf.get("NAME") or "").strip()
        phone = normalize_wa(buf.get("PHONE") or "")
        plan = (buf.get("PLAN") or "").lower()
        day, mon = buf.get("DOB_DAY"), buf.get("DOB_MON")
        medical = (buf.get("MEDICAL") or "").strip()

        # Create or get client
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
            # replace existing (append=False for wizard-final overwrite)
            crud.update_client_medical(cid, medical, append=False)

        state.update({"flow": None, "await": None, "cid": None, "buffer": {}, "book": {}})
        send_whatsapp_text(wa, "✅ New client saved.")
        return _root_menu(wa)

    # default: restart
    return _start_new(wa, state)

def _capture_free_text(wa: str, state: dict, raw: str):
    field = state.get("await")
    txt = (raw or "").strip()

    # ── NEW flow capture
    if state.get("flow") == "NEW":
        buf = state.setdefault("buffer", {})
        if field == "NAME":
            if len(txt) < 2:
                return _ask_free_text(wa, "New Client", "Name seems too short — please reply with full name.", "ADMIN_INTENT_NEW")
            buf["NAME"] = txt.title()[:120]
            state["await"] = "PHONE"
            return _ask_free_text(wa, "New Client", "Reply with the client's phone (0XXXXXXXXX, +27…, or 27…).", "ADMIN_INTENT_NEW")

        if field == "PHONE":
            norm = normalize_wa(txt)
            if not norm.startswith("+27"):
                return _ask_free_text(wa, "New Client", "Please send a valid SA phone (0…, 27…, or +27…).", "ADMIN_INTENT_NEW")
            buf["PHONE"] = norm
            state["await"] = "PLAN"
            return _ask_free_text(wa, "New Client", "Reply with plan: 1x, 2x, or 3x.", "ADMIN_INTENT_NEW")

        if field == "PLAN":
            low = txt.lower()
            if low not in ("1x", "2x", "3x"):
                return _ask_free_text(wa, "New Client", "Please reply with 1x, 2x, or 3x.", "ADMIN_INTENT_NEW")
            buf["PLAN"] = low
            state["await"] = "DOB"
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
            state["await"] = "MEDICAL"
            return _ask_free_text(wa, "New Client", "Medical notes (optional). Reply '-' to skip.", "ADMIN_INTENT_NEW")

        if field == "MEDICAL":
            buf["MEDICAL"] = txt[:500]
            # Finalize
            state["await"] = "MEDICAL"  # keep pointer for _new_next guard
            return handle_admin_action(wa, "ADMIN_NEW_NEXT")

    # ── UPDATE flow capture
    if state.get("flow") == "UPDATE" and state.get("cid"):
        cid = state["cid"]
        if field == "NAME":
            if len(txt) < 2:
                return _ask_free_text(wa, "Edit Name", "Name seems too short — please reply with full name.")
            _save_name(cid, txt.title()[:120])
            state["await"] = None
            send_whatsapp_text(wa, "✅ Name updated.")
            return _update_menu(wa, cid)

        if field == "PLAN":
            low = txt.lower()
            if low not in ("1x", "2x", "3x"):
                return _ask_free_text(wa, "Edit Plan", "Please reply with 1x, 2x, or 3x.")
            _save_plan(cid, low)
            state["await"] = None
            send_whatsapp_text(wa, "✅ Plan updated.")
            return _update_menu(wa, cid)

        if field == "MEDICAL":
            crud.update_client_medical(cid, txt[:500], append=False)
            state["await"] = None
            send_whatsapp_text(wa, "✅ Medical notes updated.")
            return _update_menu(wa, cid)

        if field == "CREDITS":
            m = re.fullmatch(r"\s*([+-]?\d+)\s*", txt)
            if not m:
                return _ask_free_text(wa, "Adjust Credits", "Reply with +N or -N (e.g., +1, -2).")
            delta = int(m.group(1))
            _save_credits_delta(cid, delta)
            state["await"] = None
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
            state["await"] = None
            send_whatsapp_text(wa, "✅ DOB updated.")
            return _update_menu(wa, cid)

    # default: show root
    state["await"] = None
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
