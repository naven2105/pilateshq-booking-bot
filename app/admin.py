# app/admin.py
"""
Admin command handler.

This module supports TWO styles at the same time:

1) NEW FLOW (recommended): single-word intents and guided menus/wizards
   - "NEW", "UPDATE", "VIEW", "CANCEL", "BOOK"
   - Implemented as a small per-admin state machine + WhatsApp interactive lists/buttons.

2) LEGACY TEMPLATES (backup): exact text commands kept for now, grouped below
   - e.g., ADD CLIENT "Full Name" PHONE 0XXXXXXXXX
           SET DOB "Full Name" DD MON
           ADD NOTE "Full Name" - free text note
           CANCEL NEXT "Full Name"
           NOSHOW TODAY "Full Name"
           BOOK "Full Name" ON YYYY-MM-DD HH:MM
           SHOW CLIENTS
           SHOW SLOTS
           VIEW "Full Name"

3) NLP FALLBACKS: free-text parser in app/admin_nlp.py
   - Handles natural language like “book John on 2025-09-01 09:00”
   - Used only when not currently inside a wizard step.

You can safely remove (2) later to reduce cognitive load; for now we keep it, strongly boxed and documented.
"""

from __future__ import annotations

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
# Admin auth: single admin (Nadine) or additional numbers via ADMIN_WA_LIST
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
# Admin menu state machine (NEW FLOW)
# State layout (one per admin WA):
# ADMIN_STATE["+27..."] = {
#   "flow":  "NEW" | "UPDATE" | "CANCEL" | "VIEW" | "BOOK" | None,
#   "await": A sub-step label like "NAME" / "PLAN" / "DOB" / "MEDICAL" / "CREDITS" | None,
#   "cid":   Selected client id for UPDATE/VIEW/CANCEL/BOOK,
#   "buffer": transient dict for wizard capture,
#   "book":   dict for booking selections: {"type": "...", "mode": "...", "slot_id": ...}
# }
# ──────────────────────────────────────────────────────────────────────────────

ADMIN_STATE: dict[str, dict] = {}

def _get_state(wa: str) -> dict:
    st = ADMIN_STATE.get(wa)
    if not st:
        st = {"flow": None, "await": None, "cid": None, "buffer": {}, "book": {}}
        ADMIN_STATE[wa] = st
    return st

def _set_state(wa: str, **kwargs):
    st = _get_state(wa)
    st.update(kwargs)
    ADMIN_STATE[wa] = st


# ──────────────────────────────────────────────────────────────────────────────
# NEW FLOW: compact helpers (menus, pickers, save actions)
# ──────────────────────────────────────────────────────────────────────────────

def _root_menu(to: str):
    """Top-level admin menu for the new flow."""
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
    """Shows latest clients (or a name search) as a WhatsApp list."""
    rows = []
    matches = crud.find_clients_by_name(q, limit=10) if q else crud.list_clients(limit=10)
    for c in matches:
        rows.append({
            "id": f"ADMIN_PICK_CLIENT_{c['id']}",
            "title": (c["name"] or "(no name)")[:24],
            "description": f"{c['wa_number']} • {c.get('credits',0)} cr"
        })
    body = "Pick a client:" + (f' (search="{q}")' if q else "")
    return send_whatsapp_list(to, title, body, "ADMIN_CLIENTS", rows or [{"id": "ADMIN_ROOT", "title": "⬅️ Back"}])

def _show_profile(to: str, cid: int):
    """Text-only profile view for a selected client."""
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
    """Field-by-field update menu for the selected client."""
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
    """Show a single ‘reply with text’ prompt with a back button."""
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
    """List next open slots (DB helper in app/booking.py)."""
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
# Button token helpers (used in legacy part too)
# ──────────────────────────────────────────────────────────────────────────────

def _build_token(action: str, **kwargs) -> str:
    parts = [action.upper()]
    for k, v in kwargs.items():
        parts.append(f"{k}={quote(str(v))}")
    return "ADMIN_CONFIRM__" + "|".join(parts)

def _parse_token(payload: str) -> tuple[str, dict]:
    if payload.startswith("ADMIN_CONFIRM__"):
        payload = payload[len("ADMIN_CONFIRM__"):]
    pieces = payload.split("|")
    action = pieces[0].upper() if pieces else ""
    args = {}
    for p in pieces[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            args[k] = unquote(v)
    return action, args


# ──────────────────────────────────────────────────────────────────────────────
# LEGACY TEMPLATES (BACKUP) — kept for now, grouped & clearly labeled
# NOTE: Prefer the new single-word flow; these exact-text commands remain for continuity.
# ──────────────────────────────────────────────────────────────────────────────

TEMPLATE_HELP = (
    "🧭 *Admin Command Templates (exact)*\n"
    "• ADD CLIENT \"Full Name\" PHONE 0XXXXXXXXX\n"
    "• SET DOB \"Full Name\" DD MON      (e.g., 21 MAY)\n"
    "• ADD NOTE \"Full Name\" - free text note\n"
    "• CANCEL NEXT \"Full Name\"\n"
    "• NOSHOW TODAY \"Full Name\"\n"
    "• BOOK \"Full Name\" ON YYYY-MM-DD HH:MM\n"
    "• SHOW CLIENTS\n"
    "• SHOW SLOTS\n"
    "• VIEW \"Full Name\""
)

def _show_template(recipient: str, error_msg: str | None = None):
    if error_msg:
        send_whatsapp_text(recipient, f"⚠️ {error_msg}\n\n{TEMPLATE_HELP}")
    else:
        send_whatsapp_text(recipient, TEMPLATE_HELP)

def _legacy_month_to_int(mon: str) -> int | None:
    mon = mon.strip().lower()
    table = {
        "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
        "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
        "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10,
        "nov": 11, "november": 11, "dec": 12, "december": 12
    }
    return table.get(mon)

def _legacy_resolve_single_client(sender: str, name: str, next_prefix: str | None = None):
    matches = crud.find_clients_by_name(name, limit=6)
    if not matches:
        send_whatsapp_text(sender, f"⚠️ No client matching “{name}”.")
        return None
    if len(matches) == 1 or not next_prefix:
        return matches[0]
    rows = [{"id": f"{next_prefix}{m['id']}", "title": m["name"][:24], "description": m["wa_number"]} for m in matches]
    send_whatsapp_list(sender, "Who do you mean?", "Pick a client:", "ADMIN_MENU", rows)
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

def handle_admin_action(sender: str, text: str):
    """Single entry for ALL admin input (interactive + plain text)."""
    if not _is_admin(sender):
        return send_whatsapp_text(sender, "⛔ Only Nadine (admin) can perform admin functions.")

    wa = normalize_wa(sender)
    state = _get_state(wa)

    raw = (text or "").strip()
    up = raw.upper()
    logging.info(f"[ADMIN CMD] '{raw}' (flow={state['flow']} await={state['await']} cid={state['cid']})")

    # ──────────────────────────────────────────────────────────────────
    # NEW FLOW — top-level intents via interactive buttons
    # ──────────────────────────────────────────────────────────────────
    if up == "ADMIN_INTENT_NEW":
        _set_state(wa, flow="NEW", await="NAME", cid=None, buffer={}, book={})
        return _ask_free_text(wa, "New Client", "Reply with the client's full name.", "ADMIN_INTENT_NEW")

    if up == "ADMIN_INTENT_UPDATE":
        _set_state(wa, flow="UPDATE", await=None)
        return _client_picker(wa, "Update: pick client")

    if up == "ADMIN_INTENT_CANCEL":
        _set_state(wa, flow="CANCEL", await=None)
        return _client_picker(wa, "Cancel: pick client")

    if up == "ADMIN_INTENT_VIEW":
        _set_state(wa, flow="VIEW", await=None)
        return _client_picker(wa, "View: pick client")

    if up == "ADMIN_INTENT_BOOK":
        _set_state(wa, flow="BOOK", await=None)
        return _client_picker(wa, "Book: pick client")

    # Select client from picker (new flow)
    if up.startswith("ADMIN_PICK_CLIENT_"):
        try:
            cid = int(up.replace("ADMIN_PICK_CLIENT_", ""))
        except ValueError:
            return send_whatsapp_text(wa, "Invalid selection.")
        _set_state(wa, cid=cid)
        if state["flow"] == "VIEW":
            return _show_profile(wa, cid)
        if state["flow"] == "UPDATE":
            return _update_menu(wa, cid)
        if state["flow"] == "CANCEL":
            # Here you can wire cancel-next or a list of upcoming sessions to pick which to cancel.
            # Kept minimal to not change behavior:
            ok = getattr(crud, "cancel_next_booking_for_client", lambda *_: False)(cid)
            return send_whatsapp_text(wa, "✅ Next session cancelled." if ok else "⚠️ No upcoming booking found.")
        if state["flow"] == "BOOK":
            return _book_type_menu(wa)
        return _root_menu(wa)

    # UPDATE field selectors
    if up in ("ADMIN_EDIT_NAME", "ADMIN_EDIT_DOB", "ADMIN_EDIT_PLAN", "ADMIN_EDIT_MEDICAL", "ADMIN_EDIT_CREDITS"):
        if not state.get("cid"):
            return _client_picker(wa, "Update: pick client")
        if up == "ADMIN_EDIT_NAME":
            _set_state(wa, await="NAME")
            return _ask_free_text(wa, "Edit Name", "Reply with the client's full name.")
        if up == "ADMIN_EDIT_DOB":
            _set_state(wa, await="DOB")
            return _ask_free_text(wa, "Edit DOB", "Reply as DD MON (e.g., 21 MAY).")
        if up == "ADMIN_EDIT_PLAN":
            _set_state(wa, await="PLAN")
            return _ask_free_text(wa, "Edit Plan", "Reply with: 1x, 2x, or 3x.")
        if up == "ADMIN_EDIT_MEDICAL":
            _set_state(wa, await="MEDICAL")
            return _ask_free_text(wa, "Edit Medical Notes", "Reply with the medical note (replaces existing).")
        if up == "ADMIN_EDIT_CREDITS":
            _set_state(wa, await="CREDITS")
            return _ask_free_text(wa, "Adjust Credits", "Reply with +N or -N (e.g., +1, -2).")

    if up == "ADMIN_DONE":
        _set_state(wa, flow=None, await=None, cid=None, buffer={}, book={})
        return _root_menu(wa)

    # BOOK selections (type → mode → slot → confirm)
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
        prof = crud.get_client_profile(st["cid"]) if st.get("cid") else None
        nm = prof["name"] if prof else "client"
        body = f"Confirm booking for {nm}\n• Type: {st['book'].get('type')}\n• Mode: {st['book'].get('mode')}\n• Slot ID: {slot_id}"
        return send_whatsapp_buttons(wa, body, [
            {"id": "ADMIN_BOOK_CONFIRM", "title": "Confirm"},
            {"id": "ADMIN_INTENT_BOOK",  "title": "Back"},
        ])

    if up == "ADMIN_BOOK_CONFIRM":
        st = _get_state(wa)
        if not (st.get("cid") and st.get("book", {}).get("slot_id")):
            return send_whatsapp_text(wa, "Missing selection.")
        prof = crud.get_client_profile(st["cid"])
        ok = booking.admin_reserve(prof["wa_number"], st["book"]["slot_id"], seats=1)
        send_whatsapp_text(wa, "✅ Booked." if ok else "⚠️ Could not book (full?).")
        st["book"] = {}
        return _update_menu(wa, st["cid"])

    # NEW wizard ‘next’ (internal)
    if up == "ADMIN_NEW_NEXT":
        return _new_next(wa, _get_state(wa))

    # ──────────────────────────────────────────────────────────────────
    # FREE-TEXT CAPTURE for active wizard field
    # ──────────────────────────────────────────────────────────────────
    if state.get("await"):
        return _capture_free_text(wa, _get_state(wa), raw)

    # ──────────────────────────────────────────────────────────────────
    # LEGACY TEMPLATES (BACKUP): exact-text commands recognized here
    # ──────────────────────────────────────────────────────────────────
    # Menu/help shortcuts from old flow
    if up in ("ADMIN", "ADMIN_MENU"):
        return _root_menu(wa)  # map to new root
    if up in ("HELP", "ADMIN_HELP", "?"):
        return _show_template(wa, None)
    if up in ("SHOW CLIENTS", "LIST CLIENTS", "ADMIN_LIST_CLIENTS"):
        clients = crud.list_clients(limit=20)
        rows = [{"id": f"ADMIN_PICK_CLIENT_{c['id']}", "title": c["name"][:24], "description": f"{c['wa_number']} • {c.get('credits',0)} cr"} for c in clients]
        return send_whatsapp_list(wa, "Clients", "Latest clients:", "ADMIN_MENU",
                                  rows or [{"id": "ADMIN_ROOT", "title": "⬅️ Menu"}])
    if up in ("SHOW SLOTS", "LIST SLOTS", "ADMIN_LIST_SLOTS"):
        days = crud.list_days_with_open_slots(days=21, limit_days=10)
        rows = [{"id": f"ADMIN_DAY_{d['session_date']}", "title": str(d['session_date']), "description": f"{d['slots']} open"} for d in days]
        return send_whatsapp_list(wa, "Open Slots", "Choose a day:", "ADMIN_MENU",
                                  rows or [{"id": "ADMIN_ROOT", "title": "⬅️ Menu"}])

    # 1) ADD CLIENT "Full Name" PHONE 0XXXXXXXXX
    m = re.fullmatch(r'\s*ADD\s+CLIENT\s+"(.+?)"\s+PHONE\s+([+\d][\d\s-]+)\s*', raw, flags=re.IGNORECASE)
    if m:
        name = m.group(1).strip()
        phone = re.sub(r"[\s-]+", "", m.group(2))
        summary = f"Add client:\n• Name: {name}\n• Phone: {phone}"
        token = _build_token("ADD_CLIENT", name=name, phone=phone)
        return send_whatsapp_buttons(wa, summary, [
            {"id": token, "title": "Confirm"},
            {"id": "ADMIN_ABORT", "title": "Cancel"},
        ])

    # 2) SET DOB "Full Name" DD MON
    m = re.fullmatch(r'\s*SET\s+DOB\s+"(.+?)"\s+(\d{1,2})\s+([A-Za-z]{3,})\s*', raw, flags=re.IGNORECASE)
    if m:
        name, day_s, mon_s = m.group(1).strip(), m.group(2), m.group(3)
        mon_i = _legacy_month_to_int(mon_s)
        if mon_i is None:
            return _show_template(wa, "Invalid month (use JAN, FEB, …).")
        client = _legacy_resolve_single_client(wa, name)
        if not client:
            return
        summary = f"Set DOB:\n• Client: {client['name']}\n• DOB: {day_s} {mon_s.upper()}"
        token = _build_token("SET_DOB", cid=client["id"], day=day_s, mon=mon_i)
        return send_whatsapp_buttons(wa, summary, [
            {"id": token, "title": "Confirm"},
            {"id": "ADMIN_ABORT", "title": "Cancel"},
        ])

    # 3) ADD NOTE "Full Name" - free text
    m = re.fullmatch(r'\s*ADD\s+NOTE\s+"(.+?)"\s*-\s*(.+)\s*', raw, flags=re.IGNORECASE)
    if m:
        name, note = m.group(1).strip(), m.group(2).strip()
        client = _legacy_resolve_single_client(wa, name)
        if not client:
            return
        summary = f"Add Note:\n• Client: {client['name']}\n• Note: {note}"
        token = _build_token("ADD_NOTE", cid=client["id"], note=note)
        return send_whatsapp_buttons(wa, summary, [
            {"id": token, "title": "Confirm"},
            {"id": "ADMIN_ABORT", "title": "Cancel"},
        ])

    # 4) CANCEL NEXT "Full Name"
    m = re.fullmatch(r'\s*CANCEL\s+NEXT\s+"(.+?)"\s*', raw, flags=re.IGNORECASE)
    if m:
        name = m.group(1).strip()
        client = _legacy_resolve_single_client(wa, name)
        if not client:
            return
        summary = f"Cancel next session:\n• Client: {client['name']}"
        token = _build_token("CANCEL_NEXT", cid=client["id"])
        return send_whatsapp_buttons(wa, summary, [
            {"id": token, "title": "Confirm"},
            {"id": "ADMIN_ABORT", "title": "Cancel"},
        ])

    # 5) NOSHOW TODAY "Full Name"
    m = re.fullmatch(r'\s*NOSHOW\s+TODAY\s+"(.+?)"\s*', raw, flags=re.IGNORECASE)
    if m:
        name = m.group(1).strip()
        client = _legacy_resolve_single_client(wa, name)
        if not client:
            return
        summary = f"No-show today:\n• Client: {client['name']}"
        token = _build_token("NOSHOW_TODAY", cid=client["id"])
        return send_whatsapp_buttons(wa, summary, [
            {"id": token, "title": "Confirm"},
            {"id": "ADMIN_ABORT", "title": "Cancel"},
        ])

    # 6) BOOK "Full Name" ON YYYY-MM-DD HH:MM
    m = re.fullmatch(r'\s*BOOK\s+"(.+?)"\s+ON\s+(\d{4}-\d{2}-\d{2})\s+([0-2]?\d:\d{2})\s*', raw, flags=re.IGNORECASE)
    if m:
        name, dstr, hhmm = m.group(1).strip(), m.group(2), m.group(3)
        client = _legacy_resolve_single_client(wa, name)
        if not client:
            return
        summary = f"Book session:\n• Client: {client['name']}\n• When: {dstr} {hhmm}"
        token = _build_token("BOOK_DT", cid=client["id"], d=dstr, t=hhmm)
        return send_whatsapp_buttons(wa, summary, [
            {"id": token, "title": "Confirm"},
            {"id": "ADMIN_ABORT", "title": "Cancel"},
        ])

    # 7) VIEW "Full Name"
    m = re.fullmatch(r'\s*VIEW\s+"(.+?)"\s*', raw, flags=re.IGNORECASE)
    if m:
        name = m.group(1).strip()
        client = _legacy_resolve_single_client(wa, name)
        if not client:
            return
        return _show_profile(wa, client["id"])

    # Old interactive “pick day → pick slot” follow-ons
    if raw.startswith("ADMIN_DAY_"):
        d = raw.replace("ADMIN_DAY_", "")
        try:
            slots = crud.list_slots_for_day(date.fromisoformat(d))
            rows = [{"id": f"ADMIN_SLOT_{r['id']}", "title": str(r["start_time"]), "description": f"seats {r['seats_left']}"} for r in slots]
            return send_whatsapp_list(wa, f"Slots {d}", "Pick a slot:", "ADMIN_MENU",
                                      rows or [{"id": "ADMIN_ROOT", "title": "⬅️ Menu"}])
        except Exception as e:
            logging.exception(e)
            return _root_menu(wa)

    if raw.startswith("ADMIN_VIEW_"):
        cid_s = raw.replace("ADMIN_VIEW_", "")
        cid = int(cid_s) if cid_s.isdigit() else None
        return _show_profile(wa, cid) if cid else send_whatsapp_text(wa, "Client not found.")

    # Button confirmations for the legacy templates
    if raw.startswith("ADMIN_CONFIRM__"):
        action, args = _parse_token(raw)
        logging.info(f"[ADMIN CONFIRM] action={action} args={args}")
        try:
            if action == "ADD_CLIENT":
                res = crud.create_client(args["name"], normalize_wa(args["phone"]))
                if not res:
                    return send_whatsapp_text(wa, "⚠️ Could not add client.")
                prof = crud.get_client_profile(res["id"])
                return _show_profile(wa, prof["id"])

            if action == "SET_DOB":
                ok = crud.update_client_dob(int(args["cid"]), int(args["day"]), int(args["mon"]))
                return send_whatsapp_text(wa, "✅ DOB updated." if ok else "⚠️ Update failed.")

            if action == "ADD_NOTE":
                ok = crud.update_client_medical(int(args["cid"]), args["note"], append=True)
                return send_whatsapp_text(wa, "✅ Note added." if ok else "⚠️ Update failed.")

            if action == "CANCEL_NEXT":
                ok = crud.cancel_next_booking_for_client(int(args["cid"]))
                return send_whatsapp_text(wa, "✅ Next session cancelled. (Credit +1)") if ok else send_whatsapp_text(wa, "⚠️ No upcoming booking found.")

            if action == "NOSHOW_TODAY":
                ok = crud.mark_no_show_today(int(args["cid"]))
                return send_whatsapp_text(wa, "✅ No-show recorded.") if ok else send_whatsapp_text(wa, "⚠️ No booking found today.")

            if action == "BOOK_DT":
                sess = crud.find_session_by_date_time(date.fromisoformat(args["d"]), args["t"])
                if not sess:
                    return send_whatsapp_text(wa, "⚠️ No matching session found.")
                ok = crud.create_booking(sess["id"], int(args["cid"]), seats=1, status="confirmed")
                return send_whatsapp_text(wa, "✅ Booked.") if ok else send_whatsapp_text(wa, "⚠️ Could not book (full?).")

        except Exception as e:
            logging.exception(e)
            return send_whatsapp_text(wa, "⚠️ Error performing action.")

    if raw == "ADMIN_ABORT":
        return send_whatsapp_text(wa, "Cancelled.")

    # ──────────────────────────────────────────────────────────────────
    # NLP FALLBACKS (only when NOT in an active wizard)
    # ──────────────────────────────────────────────────────────────────
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
                return send_whatsapp_text(wa, "✅ Recurring booking stub (to be wired).")

    # If nothing matched, show the new root menu (keeps UX consistent)
    return _root_menu(wa)


# ──────────────────────────────────────────────────────────────────────────────
# NEW CLIENT WIZARD (NEW FLOW)
# ──────────────────────────────────────────────────────────────────────────────

def _new_next(wa: str, state: dict):
    """Internal step-through for the NEW client wizard."""
    step = state.get("await")
    buf = state.get("buffer", {})
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

        _set_state(wa, flow=None, await=None, cid=None, buffer={}, book={})
        send_whatsapp_text(wa, "✅ New client saved.")
        return _root_menu(wa)

    # default: restart on unexpected state
    _set_state(wa, await="NAME", buffer={})
    return _ask_free_text(wa, "New Client", "Reply with the client's full name.", "ADMIN_INTENT_NEW")


def _capture_free_text(wa: str, state: dict, raw: str):
    """Collects the text reply for whichever wizard field we are waiting on."""
    field = state.get("await")
    txt = (raw or "").strip()

    # NEW flow fields
    if state.get("flow") == "NEW":
        buf = state.setdefault("buffer", {})
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
            mon_i = _legacy_month_to_int(mon_s)
            if mon_i is None:
                return _ask_free_text(wa, "New Client", "Month must be JAN, FEB, …", "ADMIN_INTENT_NEW")
            buf["DOB_DAY"], buf["DOB_MON"] = day_s, mon_i
            _set_state(wa, await="MEDICAL")
            return _ask_free_text(wa, "New Client", "Medical notes (optional). Reply '-' to skip.", "ADMIN_INTENT_NEW")

        if field == "MEDICAL":
            buf["MEDICAL"] = txt[:500]
            _set_state(wa, await="MEDICAL")  # keep pointer for _new_next guard
            return handle_admin_action(wa, "ADMIN_NEW_NEXT")

    # UPDATE flow fields
    if state.get("flow") == "UPDATE" and state.get("cid"):
        cid = state["cid"]
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
            mon_i = _legacy_month_to_int(mon_s)
            if mon_i is None:
                return _ask_free_text(wa, "Edit DOB", "Month must be JAN, FEB, …")
            crud.update_client_dob(cid, int(day_s), int(mon_i))
            _set_state(wa, await=None)
            send_whatsapp_text(wa, "✅ DOB updated.")
            return _update_menu(wa, cid)

    # fall-through to root if a stray text appears
    _set_state(wa, await=None)
    return _root_menu(wa)
