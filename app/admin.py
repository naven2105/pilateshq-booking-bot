# app/admin.py
from __future__ import annotations

import os
import re
import logging
from datetime import date
from typing import Optional, Dict, Any

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
# Intents & state
# ──────────────────────────────────────────────────────────────────────────────
INTENTS = {"NEW", "UPDATE", "CANCEL", "VIEW", "BOOK", "CANCEL_INBOX"}

# In-memory per-admin state
ADMIN_STATE: Dict[str, Dict[str, Any]] = {}

def _get_state(wa: str) -> Dict[str, Any]:
    st = ADMIN_STATE.get(wa)
    if not st:
        st = {"flow": None, "await_": None, "cid": None, "buffer": {}, "book": {}, "page": 0}
        ADMIN_STATE[wa] = st
    return st

def _set_state(
    wa: str,
    *,
    flow: Optional[str] = None,
    await_: Optional[str] = None,
    cid: Optional[int] = None,
    buffer: Optional[dict] = None,
    book: Optional[dict] = None,
    page: Optional[int] = None,
):
    st = _get_state(wa)
    if flow is not None:
        st["flow"] = flow
    if await_ is not None:
        st["await_"] = await_
    if cid is not None or cid is None:
        st["cid"] = cid
    if buffer is not None:
        st["buffer"] = buffer
    if book is not None:
        st["book"] = book
    if page is not None:
        st["page"] = max(0, int(page))

# ──────────────────────────────────────────────────────────────────────────────
# Root & common UIs
# ──────────────────────────────────────────────────────────────────────────────
def _root_menu(to: str):
    return send_whatsapp_list(
        to, "Admin", "Type a single word to start or tap:", "ADMIN_ROOT",
        [
            {"id": "ADMIN_INTENT_NEW",          "title": "➕ New"},
            {"id": "ADMIN_INTENT_UPDATE",       "title": "✏️ Update"},
            {"id": "ADMIN_INTENT_CANCEL",       "title": "❌ Cancel (per client)"},
            {"id": "ADMIN_INTENT_VIEW",         "title": "👁️ View"},
            {"id": "ADMIN_INTENT_BOOK",         "title": "📅 Book"},
            {"id": "ADMIN_INTENT_CANCEL_INBOX", "title": "🗂 Cancel Requests"},
        ],
    )

def _client_picker(to: str, title="Clients", q: str | None = None):
    rows = []
    try:
        if q:
            matches = crud.find_clients_by_name(q, limit=10)
        else:
            matches = getattr(crud, "list_clients", lambda **_: [])(limit=10)
    except Exception:
        logging.exception("client picker failed")
        matches = []

    for c in matches or []:
        rows.append({
            "id": f"ADMIN_PICK_CLIENT_{c['id']}",
            "title": (c.get("name") or "(no name)")[:24],
            "description": f"{c.get('wa_number','')} • {c.get('credits',0)} cr"
        })
    body = "Pick a client:" + (f' (search="{q}")' if q else "")
    return send_whatsapp_list(to, title, body, "ADMIN_CLIENTS", rows or [{"id": "ADMIN_ROOT", "title": "⬅️ Back"}])

def _show_profile(to: str, cid: int):
    prof = crud.get_client_profile(cid)
    if not prof:
        return send_whatsapp_text(to, "Client not found.")
    bday = f"{(prof.get('birthday_day') or '')}-{(prof.get('birthday_month') or '')}".strip("-")
    text = (f"👤 {prof.get('name')}\n"
            f"📱 {prof.get('wa_number')}\n"
            f"📅 Plan: {prof.get('plan','')}\n"
            f"🎟️ Credits: {prof.get('credits',0)}\n"
            f"🎂 DOB: {bday or '—'}\n"
            f"📝 Notes: {prof.get('medical_notes') or '—'}")
    return send_whatsapp_text(to, text)

def _update_menu(to: str, cid: int):
    prof = crud.get_client_profile(cid)
    if not prof:
        return send_whatsapp_text(to, "Client not found.")
    subtitle = (
        f"{prof.get('name')} • {prof.get('wa_number')} • Plan {prof.get('plan') or '—'} • "
        f"{prof.get('credits',0)} cr"
    )
    return send_whatsapp_list(
        to, "Update Client", f"{subtitle}\nEdit a field:", "ADMIN_UPDATE",
        [
            {"id": "ADMIN_EDIT_NAME",    "title": "👤 Name"},
            {"id": "ADMIN_EDIT_DOB",     "title": "🎂 DOB"},
            {"id": "ADMIN_EDIT_PLAN",    "title": "📅 Plan"},
            {"id": "ADMIN_EDIT_MEDICAL", "title": "🩺 Medical Notes"},
            {"id": "ADMIN_EDIT_CREDITS", "title": "🎟️ Credits (+/-)"},
            {"id": "ADMIN_EDIT_PHONE",   "title": "📱 Phone (validated)"},
            {"id": "ADMIN_DONE",         "title": "✅ Done"},
        ],
    )

def _ask_free_text(to: str, header: str, prompt: str, back_id="ADMIN_INTENT_UPDATE"):
    return send_whatsapp_list(
        to, header, prompt, "ADMIN_BACK",
        [{"id": back_id, "title": "⬅️ Back"}]
    )

# ──────────────────────────────────────────────────────────────────────────────
# DB small helpers
# ──────────────────────────────────────────────────────────────────────────────
def _save_name(cid: int, name: str):
    with get_session() as s:
        s.execute(text("UPDATE clients SET name=:nm WHERE id=:cid"),
                  {"nm": name[:120], "cid": cid})

def _save_plan(cid: int, plan: str):
    with get_session() as s:
        s.execute(text("UPDATE clients SET plan=:p WHERE id=:cid"),
                  {"p": plan[:20], "cid": cid})

def _save_phone(cid: int, phone: str):
    norm = normalize_wa(phone)
    if not norm.startswith("+27"):
        raise ValueError("Phone must be South African format (0…, 27…, +27…)")
    with get_session() as s:
        s.execute(text("UPDATE clients SET wa_number=:w WHERE id=:cid"),
                  {"w": norm, "cid": cid})

def _save_credits_delta(cid: int, delta: int):
    crud.adjust_client_credits(cid, delta)

# ──────────────────────────────────────────────────────────────────────────────
# Booking pickers
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
# Cancel Requests Inbox (NEW)
# ──────────────────────────────────────────────────────────────────────────────
def _fmt_cancel_row(r: dict) -> tuple[str, str]:
    """Return (title, description) for a cancel request list row."""
    nm = (r.get("client_name") or "Client")[:24]
    dt = f"{r.get('session_date')} {str(r.get('start_time'))[:5]}"
    title = f"{nm} – {dt}"
    reason = r.get("reason") or r.get("via") or "request"
    desc = f"#{r.get('id')} • {reason}"
    return title, desc

def _cancel_inbox_page(to: str, page: int = 0, page_size: int = 10):
    page = max(0, int(page))
    rows = crud.list_cancel_requests(status="open", limit=page_size, offset=page * page_size)
    items = []
    for r in rows:
        title, desc = _fmt_cancel_row(r)
        items.append({"id": f"ADMIN_CANCEL_REQ_{r['id']}", "title": title, "description": desc})

    # pagination controls
    nav = []
    if page > 0:
        nav.append({"id": f"ADMIN_CANCEL_PAGE_{page-1}", "title": "⬅️ Prev"})
    if len(rows) == page_size:
        nav.append({"id": f"ADMIN_CANCEL_PAGE_{page+1}", "title": "➡️ Next"})
    if not items:
        items = [{"id": "ADMIN_ROOT", "title": "No open requests — back"}]

    body = f"Open cancel requests (page {page+1})"
    return send_whatsapp_list(to, "🗂 Cancel Requests", body, "ADMIN_CANCEL_INBOX", items + nav)

def _cancel_request_detail(to: str, rid: int):
    r = crud.get_cancel_request(rid)
    if not r:
        return send_whatsapp_text(to, f"Cancel request #{rid} not found.")
    title = f"Cancel request #{rid}"
    nm = r.get("client_name") or "Client"
    dt = f"{r.get('session_date')} {str(r.get('start_time'))[:5]}"
    rsn = r.get("reason") or "—"
    txt = (f"👤 {nm}\n"
           f"🗓 {dt}\n"
           f"🧾 Booking #{r.get('booking_id')}\n"
           f"📝 Reason: {rsn}\n\n"
           f"What would you like to do?")
    return send_whatsapp_buttons(to, txt, [
        {"id": f"ADMIN_CANCEL_REQ_CONFIRM_{rid}", "title": "✅ Confirm"},
        {"id": f"ADMIN_CANCEL_REQ_RESCH_{rid}",   "title": "📅 Reschedule"},
        {"id": f"ADMIN_CANCEL_REQ_DECLINE_{rid}", "title": "🚫 Decline"},
        {"id": f"ADMIN_INTENT_CANCEL_INBOX",      "title": "⬅️ Back to inbox"},
    ])

# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────
def handle_admin_action(sender: str, text_in: str):
    if not _is_admin(sender):
        return send_whatsapp_text(sender, "⛔ Only admin can perform admin functions.")

    wa = normalize_wa(sender)
    state = _get_state(wa)

    raw = (text_in or "").strip()
    up = raw.upper()
    logging.info(f"[ADMIN CMD] '{raw}' (flow={state['flow']} await={state['await_']} cid={state['cid']} page={state.get('page',0)})")

    # ── NEW: Cancel-request decisions (from buttons)
    if up.startswith("ADMIN_CANCEL_REQ_CONFIRM_"):
        try:
            rid = int(up.split("_")[-1])
        except ValueError:
            return send_whatsapp_text(wa, "Invalid cancel id.")
        res = _admin_cancel_request_decide(wa, rid, decision="confirmed")
        # return to detail (shows success) then inbox
        _cancel_request_detail(wa, rid)
        return _cancel_inbox_page(wa, state.get("page", 0))

    if up.startswith("ADMIN_CANCEL_REQ_DECLINE_"):
        try:
            rid = int(up.split("_")[-1])
        except ValueError:
            return send_whatsapp_text(wa, "Invalid cancel id.")
        res = _admin_cancel_request_decide(wa, rid, decision="declined")
        _cancel_request_detail(wa, rid)
        return _cancel_inbox_page(wa, state.get("page", 0))

    if up.startswith("ADMIN_CANCEL_REQ_RESCH_"):
        try:
            rid = int(up.split("_")[-1])
        except ValueError:
            return send_whatsapp_text(wa, "Invalid cancel id.")
        res = _admin_cancel_request_decide(wa, rid, decision="reschedule")
        _cancel_request_detail(wa, rid)
        return _cancel_inbox_page(wa, state.get("page", 0))

    # ── NEW: Cancel Requests inbox navigation
    if up == "ADMIN_INTENT_CANCEL_INBOX":
        _set_state(wa, flow="CANCEL_INBOX", page=0)
        return _cancel_inbox_page(wa, 0)

    if up.startswith("ADMIN_CANCEL_PAGE_"):
        try:
            page = int(up.replace("ADMIN_CANCEL_PAGE_", ""))
        except ValueError:
            page = 0
        _set_state(wa, page=page)
        return _cancel_inbox_page(wa, page)

    if up.startswith("ADMIN_CANCEL_REQ_") and not any(up.startswith(x) for x in (
        "ADMIN_CANCEL_REQ_CONFIRM_", "ADMIN_CANCEL_REQ_DECLINE_", "ADMIN_CANCEL_REQ_RESCH_")):
        try:
            rid = int(up.replace("ADMIN_CANCEL_REQ_", ""))
        except ValueError:
            return send_whatsapp_text(wa, "Invalid selection.")
        return _cancel_request_detail(wa, rid)

    # ── Intent shortcuts (interactive buttons)
    if up == "ADMIN_INTENT_NEW":
        _set_state(wa, flow="NEW", await_="NAME", cid=None, buffer={}, book={}, page=0)
        return _ask_free_text(wa, "New Client", "Reply with the client's full name.", "ADMIN_INTENT_NEW")

    if up == "ADMIN_INTENT_UPDATE":
        _set_state(wa, flow="UPDATE", await_=None, page=0)
        return _client_picker(wa, "Update: pick client")

    if up == "ADMIN_INTENT_CANCEL":
        _set_state(wa, flow="CANCEL", await_=None, page=0)
        return _client_picker(wa, "Cancel: pick client")

    if up == "ADMIN_INTENT_VIEW":
        _set_state(wa, flow="VIEW", await_=None, page=0)
        return _client_picker(wa, "View: pick client")

    if up == "ADMIN_INTENT_BOOK":
        _set_state(wa, flow="BOOK", await_=None, page=0)
        return _client_picker(wa, "Book: pick client")

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
            return send_whatsapp_text(wa, "Use the 🗂 Cancel Requests inbox for client-initiated cancellations.")
        if state["flow"] == "BOOK":
            return _book_type_menu(wa)
        return _root_menu(wa)

    # ── UPDATE: edit selections
    if up in ("ADMIN_EDIT_NAME", "ADMIN_EDIT_DOB", "ADMIN_EDIT_PLAN", "ADMIN_EDIT_MEDICAL", "ADMIN_EDIT_CREDITS", "ADMIN_EDIT_PHONE"):
        if not state["cid"]:
            return _client_picker(wa, "Update: pick client")
        if up == "ADMIN_EDIT_NAME":
            state["await_"] = "NAME"
            return _ask_free_text(wa, "Edit Name", "Reply with the client's full name.")
        if up == "ADMIN_EDIT_DOB":
            state["await_"] = "DOB"
            return _ask_free_text(wa, "Edit DOB", "Reply as DD MON (e.g., 21 MAY).")
        if up == "ADMIN_EDIT_PLAN":
            state["await_"] = "PLAN"
            return _ask_free_text(wa, "Edit Plan", "Reply with: 1x, 2x, or 3x.")
        if up == "ADMIN_EDIT_MEDICAL":
            state["await_"] = "MEDICAL"
            return _ask_free_text(wa, "Edit Medical Notes", "Reply with the medical note (replaces existing).")
        if up == "ADMIN_EDIT_CREDITS":
            state["await_"] = "CREDITS"
            return _ask_free_text(wa, "Adjust Credits", "Reply with +N or -N (e.g., +1, -2).")
        if up == "ADMIN_EDIT_PHONE":
            state["await_"] = "PHONE"
            return _ask_free_text(wa, "Edit Phone", "Reply with SA phone (0XXXXXXXXX, 27…, or +27…).")
        return _update_menu(wa, state["cid"])

    if up == "ADMIN_DONE":
        _set_state(wa, flow=None, await_=None, cid=None, buffer={}, book={}, page=0)
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
        body = (
            f"Confirm booking for {nm}\n"
            f"• Type: {state['book'].get('type')}\n"
            f"• Mode: {state['book'].get('mode')}\n"
            f"• Slot ID: {slot_id}"
        )
        return send_whatsapp_buttons(wa, body, [
            {"id": f"ADMIN_BOOK_CONFIRM", "title": "Confirm"},
            {"id": "ADMIN_INTENT_BOOK",   "title": "Back"},
        ])

    if up == "ADMIN_BOOK_CONFIRM":
        if not (state.get("cid") and state.get("book", {}).get("slot_id")):
            return send_whatsapp_text(wa, "Missing selection.")
        prof = crud.get_client_profile(state["cid"])
        ok = booking.admin_reserve(prof["wa_number"], state["book"]["slot_id"], seats=1)
        if ok:
            send_whatsapp_text(wa, "✅ Booked.")
        else:
            send_whatsapp_text(wa, "⚠️ Could not book (full?).")
        state["book"] = {}
        return _update_menu(wa, state["cid"])

    # ── NEW flow driver
    if up == "ADMIN_NEW_NEXT":
        return _new_next(wa, state)

    # ── Free-text capture for awaited fields
    if state["await_"]:
        return _capture_free_text(wa, state, raw)

    # ── Single-word intents typed
    low = raw.lower()
    if low in ("new", "update", "cancel", "view", "book", "inbox"):
        map_word = {
            "new": "ADMIN_INTENT_NEW",
            "update": "ADMIN_INTENT_UPDATE",
            "cancel": "ADMIN_INTENT_CANCEL",
            "view": "ADMIN_INTENT_VIEW",
            "book": "ADMIN_INTENT_BOOK",
            "inbox": "ADMIN_INTENT_CANCEL_INBOX",
        }
        return handle_admin_action(wa, map_word[low])

    # ── NLP fallbacks
    if not state.get("await_"):
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
                return send_whatsapp_text(wa, "✅ Recurring booking stub (wire your weekly finder).")

    # Otherwise, show the root
    return _root_menu(wa)

# ──────────────────────────────────────────────────────────────────────────────
# NEW CLIENT WIZARD
# ──────────────────────────────────────────────────────────────────────────────
def _start_new(wa: str, state: dict):
    _set_state(wa, await_="NAME", buffer={}, cid=None)
    return _ask_free_text(wa, "New Client", "Reply with the client's full name.", "ADMIN_INTENT_NEW")

def _new_next(wa: str, state: dict):
    step = state.get("await_")
    buf = state.get("buffer", {})
    if step == "NAME":
        _set_state(wa, await_="PHONE")
        return _ask_free_text(wa, "New Client", "Reply with the client's phone (0XXXXXXXXX, +27…, or 27…).", "ADMIN_INTENT_NEW")
    if step == "PHONE":
        _set_state(wa, await_="PLAN")
        return _ask_free_text(wa, "New Client", "Reply with plan: 1x, 2x, or 3x.", "ADMIN_INTENT_NEW")
    if step == "PLAN":
        _set_state(wa, await_="DOB")
        return _ask_free_text(wa, "New Client", "Reply DOB as DD MON (e.g., 21 MAY).", "ADMIN_INTENT_NEW")
    if step == "DOB":
        _set_state(wa, await_="MEDICAL")
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

        _set_state(wa, flow=None, await_=None, cid=None, buffer={}, book={}, page=0)
        send_whatsapp_text(wa, "✅ New client saved.")
        return _root_menu(wa)

    return _start_new(wa, state)

def _capture_free_text(wa: str, state: dict, raw: str):
    field = state.get("await_")
    txt = (raw or "").strip()

    # NEW flow capture
    if state.get("flow") == "NEW":
        buf = state.setdefault("buffer", {})
        if field == "NAME":
            if len(txt) < 2:
                return _ask_free_text(wa, "New Client", "Name seems too short — please reply with full name.", "ADMIN_INTENT_NEW")
            buf["NAME"] = txt.title()[:120]
            state["await_"] = "PHONE"
            return _ask_free_text(wa, "New Client", "Reply with the client's phone (0XXXXXXXXX, +27…, or 27…).", "ADMIN_INTENT_NEW")

        if field == "PHONE":
            norm = normalize_wa(txt)
            if not norm.startswith("+27"):
                return _ask_free_text(wa, "New Client", "Please send a valid SA phone (0…, 27…, or +27…).", "ADMIN_INTENT_NEW")
            buf["PHONE"] = norm
            state["await_"] = "PLAN"
            return _ask_free_text(wa, "New Client", "Reply with plan: 1x, 2x, or 3x.", "ADMIN_INTENT_NEW")

        if field == "PLAN":
            low = txt.lower()
            if low not in ("1x", "2x", "3x"):
                return _ask_free_text(wa, "New Client", "Please reply with 1x, 2x, or 3x.", "ADMIN_INTENT_NEW")
            buf["PLAN"] = low
            state["await_"] = "DOB"
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
            state["await_"] = "MEDICAL"
            return _ask_free_text(wa, "New Client", "Medical notes (optional). Reply '-' to skip.", "ADMIN_INTENT_NEW")

        if field == "MEDICAL":
            buf["MEDICAL"] = txt[:500]
            state["await_"] = "MEDICAL"
            return handle_admin_action(wa, "ADMIN_NEW_NEXT")

    # UPDATE flow capture
    if state.get("flow") == "UPDATE" and state.get("cid"):
        cid = state["cid"]
        if field == "NAME":
            if len(txt) < 2:
                return _ask_free_text(wa, "Edit Name", "Name seems too short — please reply with full name.")
            _save_name(cid, txt.title()[:120])
            state["await_"] = None
            send_whatsapp_text(wa, "✅ Name updated.")
            return _update_menu(wa, cid)

        if field == "PLAN":
            low = txt.lower()
            if low not in ("1x", "2x", "3x"):
                return _ask_free_text(wa, "Edit Plan", "Please reply with 1x, 2x, or 3x.")
            _save_plan(cid, low)
            state["await_"] = None
            send_whatsapp_text(wa, "✅ Plan updated.")
            return _update_menu(wa, cid)

        if field == "MEDICAL":
            crud.update_client_medical(cid, txt[:500], append=False)
            state["await_"] = None
            send_whatsapp_text(wa, "✅ Medical notes updated.")
            return _update_menu(wa, cid)

        if field == "CREDITS":
            m = re.fullmatch(r"\s*([+-]?\d+)\s*", txt)
            if not m:
                return _ask_free_text(wa, "Adjust Credits", "Reply with +N or -N (e.g., +1, -2).")
            delta = int(m.group(1))
            _save_credits_delta(cid, delta)
            state["await_"] = None
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
            state["await_"] = None
            send_whatsapp_text(wa, "✅ DOB updated.")
            return _update_menu(wa, cid)

        if field == "PHONE":
            try:
                _save_phone(cid, txt)
            except Exception as e:
                return _ask_free_text(wa, "Edit Phone", f"{e}. Try again.")
            state["await_"] = None
            send_whatsapp_text(wa, "✅ Phone updated.")
            return _update_menu(wa, cid)

    # default
    state["await_"] = None
    return _root_menu(wa)

# ──────────────────────────────────────────────────────────────────────────────
# Cancel request decisions (admin)
# ──────────────────────────────────────────────────────────────────────────────
def _admin_cancel_request_decide(wa: str, req_id: int, decision: str):
    """
    decision ∈ {'confirmed','declined','reschedule'}
    On confirmed: mark bookings.status='cancelled', decrement sessions.booked_count, mark cancel_requests.status='confirmed', notify client.
    On declined/reschedule: mark cancel_requests.status, notify client.
    """
    try:
        req = crud.get_cancel_request(req_id)
        if not req:
            return send_whatsapp_text(wa, f"⚠️ Cancel request #{req_id} not found.")
    except Exception:
        logging.exception("get_cancel_request failed")
        return send_whatsapp_text(wa, f"⚠️ Cancel request #{req_id} not found.")

    client = crud.get_client_profile(req["client_id"]) if req.get("client_id") else None
    client_wa = normalize_wa(client["wa_number"]) if client else None
    hhmm = str(req.get("start_time"))[:5] if req.get("start_time") else "time"

    if decision == "confirmed":
        try:
            _confirm_cancel_inline(req)
            _mark_cancel_request_status(req_id, "confirmed")
            if client_wa:
                send_whatsapp_text(client_wa, f"✅ Your {hhmm} session has been cancelled. We’ll carry your credit over and help you reschedule.")
            return send_whatsapp_text(wa, f"✅ Cancelled booking #{req['booking_id']} and updated counts.")
        except Exception:
            logging.exception("confirm cancel failed")
            return send_whatsapp_text(wa, "⚠️ Failed to cancel booking. Please try again.")

    if decision == "declined":
        try:
            _mark_cancel_request_status(req_id, "declined")
            if client_wa:
                send_whatsapp_text(client_wa, f"ℹ️ Cancellation for your {hhmm} session was not approved. Please contact the studio if needed.")
            return send_whatsapp_text(wa, f"✅ Declined cancel request #{req_id}.")
        except Exception:
            logging.exception("decline cancel failed")
            return send_whatsapp_text(wa, "⚠️ Failed to update request.")

    if decision == "reschedule":
        try:
            _mark_cancel_request_status(req_id, "reschedule")
            if client_wa:
                send_whatsapp_text(client_wa, f"📅 We’ll reschedule your {hhmm} session. The studio will message you with options.")
            return send_whatsapp_text(wa, f"✅ Marked request #{req_id} for reschedule.")
        except Exception:
            logging.exception("reschedule mark failed")
            return send_whatsapp_text(wa, "⚠️ Failed to update request.")

    return send_whatsapp_text(wa, "Unknown decision.")

def _get_cancel_request_inline(req_id: int) -> Optional[dict]:
    with get_session() as s:
        row = s.execute(text("""
            SELECT
              r.id,
              r.booking_id,
              r.client_id,
              r.session_id,
              r.status,
              r.reason,
              r.via,
              r.created_at,
              s.session_date,
              s.start_time,
              c.name AS client_name
            FROM cancel_requests r
            JOIN sessions s ON s.id = r.session_id
            JOIN clients  c ON c.id = r.client_id
            WHERE r.id = :rid
        """), {"rid": req_id}).mappings().first()
        return dict(row) if row else None

def _mark_cancel_request_status(req_id: int, status: str):
    with get_session() as s:
        s.execute(text("""
            UPDATE cancel_requests
               SET status = :st
             WHERE id = :rid
        """), {"st": status, "rid": req_id})

def _confirm_cancel_inline(req: dict):
    with get_session() as s:
        b = s.execute(text("SELECT seats, session_id FROM bookings WHERE id=:bid FOR UPDATE"),
                      {"bid": req["booking_id"]}).mappings().first()
        if not b:
            raise ValueError("booking not found")
        seats = int(b.get("seats") or 1)
        sess_id = int(b["session_id"])

        s.execute(text("UPDATE bookings SET status='cancelled' WHERE id=:bid"),
                  {"bid": req["booking_id"]})

        s.execute(text("""
            UPDATE sessions
               SET booked_count = GREATEST(booked_count - :seats, 0),
                   status = CASE WHEN booked_count - :seats < capacity THEN 'open' ELSE status END
             WHERE id = :sid
        """), {"seats": seats, "sid": sess_id})

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
