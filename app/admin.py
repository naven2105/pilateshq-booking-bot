# app/admin.py
# -*- coding: utf-8 -*-
"""
Admin command handler (WhatsApp).
- Authenticates admin
- Supports single-word intents: NEW / UPDATE / CANCEL / VIEW / BOOK
- Preserves strict template fallbacks (ADD CLIENT "..." PHONE ..., etc.)
- Refined UPDATE flow:
    snapshot → choose field → show current + prompt
    → preview diff → confirm/undo → back to menu
Notes:
- We avoid "side-by-side" UI by sending a compact snapshot + prompts.
- Prompts are plain text (no "Choose" footer), diffs use 2–3 buttons.
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

# Optional NLP helpers for legacy/quick commands
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
# In-memory per-admin state (simple)
# ──────────────────────────────────────────────────────────────────────────────
# ADMIN_STATE["+27..."] = {
#   "flow": "NEW" | "UPDATE" | "CANCEL" | "VIEW" | "BOOK",
#   "await": "... field or step ...",
#   "cid": int | None,              # current selected client id
#   "buffer": dict,                 # transient values for wizards/edits
#   "book": dict,                   # booking choices
#   "undo": { "field": str, "cid": int, "old": Any } | None,  # last change
# }
ADMIN_STATE: dict[str, dict] = {}


# ──────────────────────────────────────────────────────────────────────────────
# Root menu + intent shortcuts
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
    """List latest or name-filtered clients as a list picker."""
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


# ──────────────────────────────────────────────────────────────────────────────
# Profile snapshot + menus
# ──────────────────────────────────────────────────────────────────────────────
def _profile_text(cid: int) -> str:
    prof = crud.get_client_profile(cid)
    if not prof:
        return "Client not found."
    bday = f"{(prof.get('birthday_day') or '')}-{(prof.get('birthday_month') or '')}".strip("-")
    text = (f"👤 {prof['name']}\n"
            f"📱 {prof['wa_number']}\n"
            f"🎂 DOB: {bday or '—'}\n"
            f"🎟️ Credits: {prof.get('credits',0)}\n"
            f"📝 Notes: {(prof.get('medical_notes') or '—')[:300]}")
    return text


def _show_profile(to: str, cid: int):
    return send_whatsapp_text(to, _profile_text(cid))


def _update_menu(to: str, cid: int):
    """Show a snapshot (text) + a list of editable fields (list)."""
    prof = crud.get_client_profile(cid)
    if not prof:
        return send_whatsapp_text(to, "Client not found.")

    # First the snapshot as plain text
    send_whatsapp_text(to, "🔧 *Update Client*\n" + _profile_text(cid))

    # Then the edit list
    return send_whatsapp_list(
        to, "Edit fields", f"What do you want to change for {prof['name']}?", "ADMIN_UPDATE",
        [
            {"id": "ADMIN_EDIT_NAME",    "title": "👤 Name"},
            {"id": "ADMIN_EDIT_PHONE",   "title": "📱 Phone"},
            {"id": "ADMIN_EDIT_DOB",     "title": "🎂 DOB"},
            {"id": "ADMIN_EDIT_MEDICAL", "title": "🩺 Medical Notes"},
            {"id": "ADMIN_EDIT_CREDITS", "title": "🎟️ Credits (+/-)"},
            {"id": "ADMIN_DONE",         "title": "✅ Done"},
        ],
    )


def _ask_text_prompt(to: str, header: str, prompt: str):
    """Send a plain text prompt (no list) so Nadine replies directly."""
    return send_whatsapp_text(to, f"*{header}*\n{prompt}\n\nType *CANCEL* to abort.")


# ──────────────────────────────────────────────────────────────────────────────
# Low-level updates (SQL via get_session)
# ──────────────────────────────────────────────────────────────────────────────
def _save_name(cid: int, name: str):
    with get_session() as s:
        s.execute(text("UPDATE clients SET name=:nm WHERE id=:cid"),
                  {"nm": name[:120], "cid": cid})

def _save_phone(cid: int, wa_number: str):
    with get_session() as s:
        s.execute(text("UPDATE clients SET wa_number=:wa WHERE id=:cid"),
                  {"wa": wa_number, "cid": cid})

def _save_dob(cid: int, day: int, month: int):
    crud.update_client_dob(cid, int(day), int(month))

def _save_medical(cid: int, note: str, append: bool):
    crud.update_client_medical(cid, note[:500], append=append)

def _adjust_credits(cid: int, delta: int):
    crud.adjust_client_credits(cid, delta)


# ──────────────────────────────────────────────────────────────────────────────
# Duplicate checks (gentle warnings)
# ──────────────────────────────────────────────────────────────────────────────
def _dup_by_phone(wa: str, exclude_cid: int | None = None) -> bool:
    with get_session() as s:
        q = "SELECT id FROM clients WHERE wa_number = :wa"
        params = {"wa": wa}
        if exclude_cid:
            q += " AND id <> :cid"
            params["cid"] = exclude_cid
        r = s.execute(text(q), params).first()
        return bool(r)

def _dup_by_name(name: str, exclude_cid: int | None = None) -> bool:
    with get_session() as s:
        q = "SELECT id FROM clients WHERE LOWER(name) = LOWER(:nm)"
        params = {"nm": name}
        if exclude_cid:
            q += " AND id <> :cid"
            params["cid"] = exclude_cid
        r = s.execute(text(q), params).first()
        return bool(r)


# ──────────────────────────────────────────────────────────────────────────────
# Booking menus (as before)
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
# Month helper
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


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────
def handle_admin_action(sender: str, text: str):
    """Main dispatcher for admin messages & interactive IDs."""
    if not _is_admin(sender):
        return send_whatsapp_text(sender, "⛔ Only Nadine (admin) can perform admin functions.")

    wa = normalize_wa(sender)
    state = ADMIN_STATE.get(wa) or {"flow": None, "await": None, "cid": None, "buffer": {}, "book": {}, "undo": None}
    ADMIN_STATE[wa] = state

    raw = (text or "").strip()
    up = raw.upper()
    logging.info(f"[ADMIN CMD] '{raw}' (flow={state.get('flow')} await={state.get('await')} cid={state.get('cid')})")

    # ── Intent shortcuts (interactive list taps)
    if up == "ADMIN_INTENT_NEW":
        state["flow"], state["await"], state["cid"], state["buffer"], state["book"], state["undo"] = "NEW", "NAME", None, {}, {}, None
        return _ask_text_prompt(wa, "New Client", "Reply with the client's *full name*.")
    if up == "ADMIN_INTENT_UPDATE":
        state["flow"], state["await"] = "UPDATE", None
        return _client_picker(wa, "Update: pick client")
    if up == "ADMIN_INTENT_CANCEL":
        state["flow"], state["await"] = "CANCEL", None
        return _client_picker(wa, "Cancel: pick client")
    if up == "ADMIN_INTENT_VIEW":
        state["flow"], state["await"] = "VIEW", None
        return _client_picker(wa, "View: pick client")
    if up == "ADMIN_INTENT_BOOK":
        state["flow"], state["await"] = "BOOK", None
        return _client_picker(wa, "Book: pick client")

    # ── Client selection
    if up.startswith("ADMIN_PICK_CLIENT_"):
        try:
            cid = int(up.replace("ADMIN_PICK_CLIENT_", ""))
        except ValueError:
            return send_whatsapp_text(wa, "Invalid selection.")
        state["cid"] = cid
        if state["flow"] == "VIEW":
            return _show_profile(wa, cid)
        if state["flow"] == "UPDATE":
            state["await"] = None
            return _update_menu(wa, cid)
        if state["flow"] == "CANCEL":
            # Needs your CRUD helper if you want: cancel all/upcoming etc.
            return send_whatsapp_text(wa, "Cancel-by-client not wired yet (stub).")
        if state["flow"] == "BOOK":
            return _book_type_menu(wa)
        return _root_menu(wa)

    # ── UPDATE: choose field (now with refined prompts)
    if up in ("ADMIN_EDIT_NAME", "ADMIN_EDIT_PHONE", "ADMIN_EDIT_DOB", "ADMIN_EDIT_MEDICAL", "ADMIN_EDIT_CREDITS"):
        if not state.get("cid"):
            return _client_picker(wa, "Update: pick client")
        cid = state["cid"]
        prof = crud.get_client_profile(cid)
        if not prof:
            return send_whatsapp_text(wa, "Client not found.")

        if up == "ADMIN_EDIT_NAME":
            state["await"] = "U_NAME_INPUT"
            return _ask_text_prompt(wa, "Edit Name",
                                    f"Current: *{prof['name']}*\nReply with the *new full name*.")

        if up == "ADMIN_EDIT_PHONE":
            state["await"] = "U_PHONE_INPUT"
            return _ask_text_prompt(wa, "Edit Phone",
                                    f"Current: *{prof['wa_number']}*\nReply with the *new SA phone* (0…, 27…, or +27…).")

        if up == "ADMIN_EDIT_DOB":
            state["await"] = "U_DOB_INPUT"
            bday = f"{(prof.get('birthday_day') or '')}-{(prof.get('birthday_month') or '')}".strip("-") or "—"
            return _ask_text_prompt(wa, "Edit DOB",
                                    f"Current: *{bday}*\nReply as *DD MON* (e.g., 21 MAY).")

        if up == "ADMIN_EDIT_MEDICAL":
            state["await"] = None
            current = prof.get("medical_notes") or "—"
            # show small submenu as buttons: View / Append / Replace
            send_whatsapp_text(wa, f"*Medical Notes*\nCurrent (first 300 chars):\n{current[:300]}")
            return send_whatsapp_list(
                wa, "Medical Notes", "Choose how to modify:", "ADMIN_MEDICAL",
                [
                    {"id": "ADMIN_MEDICAL_APPEND",  "title": "➕ Append"},
                    {"id": "ADMIN_MEDICAL_REPLACE", "title": "♻️ Replace"},
                    {"id": "ADMIN_UPDATE_BACK",     "title": "⬅️ Back"},
                ],
            )

        if up == "ADMIN_EDIT_CREDITS":
            state["await"] = None
            return send_whatsapp_list(
                wa, "Adjust Credits", "Quick adjust or choose Custom:", "ADMIN_CREDITS",
                [
                    {"id": "ADMIN_CREDITS_APPLY_+1", "title": "+1"},
                    {"id": "ADMIN_CREDITS_APPLY_+2", "title": "+2"},
                    {"id": "ADMIN_CREDITS_APPLY_-1", "title": "-1"},
                    {"id": "ADMIN_CREDITS_APPLY_-2", "title": "-2"},
                    {"id": "ADMIN_CREDITS_CUSTOM",   "title": "✍️ Custom…"},
                    {"id": "ADMIN_UPDATE_BACK",      "title": "⬅️ Back"},
                ],
            )

    # Submenu actions for Medical Notes
    if up in ("ADMIN_MEDICAL_APPEND", "ADMIN_MEDICAL_REPLACE"):
        if not state.get("cid"):
            return _client_picker(wa, "Update: pick client")
        state["await"] = "U_MEDICAL_APPEND" if up.endswith("APPEND") else "U_MEDICAL_REPLACE"
        mode = "append a new note" if up.endswith("APPEND") else "replace notes"
        return _ask_text_prompt(wa, "Medical Notes", f"Reply with the text to *{mode}*.")

    if up == "ADMIN_UPDATE_BACK":
        if not state.get("cid"):
            return _client_picker(wa, "Update: pick client")
        return _update_menu(wa, state["cid"])

    # Quick credits
    if up.startswith("ADMIN_CREDITS_APPLY_"):
        if not state.get("cid"):
            return _client_picker(wa, "Update: pick client")
        cid = state["cid"]
        delta_str = up.replace("ADMIN_CREDITS_APPLY_", "")
        try:
            delta = int(delta_str)
        except ValueError:
            return send_whatsapp_text(wa, "Invalid credits value.")
        # Save with undo support:
        prof = crud.get_client_profile(cid)
        old = prof.get("credits", 0)
        _adjust_credits(cid, delta)
        new = old + delta
        state["undo"] = {"field": "credits", "cid": cid, "old": old}
        send_whatsapp_buttons(
            wa,
            f"✅ Credits updated: {old} → {new}\nUndo?",
            [
                {"id": "ADMIN_UNDO_LAST", "title": "↩️ Undo"},
                {"id": "ADMIN_UPDATE_BACK", "title": "Back"},
            ]
        )
        return

    if up == "ADMIN_CREDITS_CUSTOM":
        if not state.get("cid"):
            return _client_picker(wa, "Update: pick client")
        state["await"] = "U_CREDITS_INPUT"
        return _ask_text_prompt(wa, "Adjust Credits", "Reply with +N or -N (e.g., +1, -2).")

    # Undo last change (if stored)
    if up == "ADMIN_UNDO_LAST":
        undo = state.get("undo")
        if not undo:
            return send_whatsapp_text(wa, "Nothing to undo.")
        cid = undo.get("cid")
        field = undo.get("field")
        old = undo.get("old")
        if field == "name":
            _save_name(cid, old)
        elif field == "wa_number":
            _save_phone(cid, old)
        elif field == "dob":
            try:
                d, m = old  # tuple (day, month)
                _save_dob(cid, d, m)
            except Exception:
                pass
        elif field == "medical_notes":
            # Full revert (replace with old)
            _save_medical(cid, old or "", append=False)
        elif field == "credits":
            prof = crud.get_client_profile(cid)
            now = prof.get("credits", 0)
            delta = (old or 0) - now
            if delta:
                _adjust_credits(cid, delta)
        state["undo"] = None
        send_whatsapp_text(wa, "↩️ Reverted.")
        return _update_menu(wa, cid)

    # Done (reset) from update menu
    if up == "ADMIN_DONE":
        state["flow"] = state["await"] = None
        state["cid"] = None
        state["buffer"] = {}
        state["book"] = {}
        state["undo"] = None
        return _root_menu(wa)

    # ── BOOK flow (unchanged core)
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
        body = (f"Confirm booking for {nm}\n"
                f"• Type: {state['book'].get('type')}\n"
                f"• Mode: {state['book'].get('mode')}\n"
                f"• Slot ID: {slot_id}")
        return send_whatsapp_buttons(wa, body, [
            {"id": "ADMIN_BOOK_CONFIRM", "title": "Confirm"},
            {"id": "ADMIN_INTENT_BOOK",  "title": "Back"},
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

    # ──────────────────────────────────────────────────────────────────────
    # Text input capture (NEW & UPDATE flows)
    # ──────────────────────────────────────────────────────────────────────
    if state.get("await"):
        # Allow cancel
        if raw.strip().upper() == "CANCEL":
            state["await"] = None
            return _update_menu(wa, state["cid"]) if state.get("flow") == "UPDATE" and state.get("cid") else _root_menu(wa)

        # NEW client wizard (kept minimal; you previously discussed removing plan/credits here)
        if state.get("flow") == "NEW":
            buf = state.setdefault("buffer", {})
            step = state["await"]

            if step == "NAME":
                if len(raw.strip()) < 2:
                    return _ask_text_prompt(wa, "New Client", "Name seems too short — reply with *full name*.")
                buf["NAME"] = raw.strip().title()[:120]
                state["await"] = "PHONE"
                return _ask_text_prompt(wa, "New Client", "Reply with the *phone* (0…, 27…, or +27…).")

            if step == "PHONE":
                norm = normalize_wa(raw)
                if not norm.startswith("+27"):
                    return _ask_text_prompt(wa, "New Client", "Please send a valid SA phone (0…, 27…, or +27…).")
                # Create or fetch:
                row = crud.create_client(buf["NAME"], norm) or crud.get_or_create_client(norm)
                cid = row["id"]
                # Optional: ask DOB then Medical; to keep lean we stop here
                state["flow"] = state["await"] = None
                state["cid"] = None
                state["buffer"] = {}
                return send_whatsapp_text(wa, "✅ New client saved.")

        # UPDATE flow inputs with preview/confirm
        if state.get("flow") == "UPDATE" and state.get("cid"):
            cid = state["cid"]
            prof = crud.get_client_profile(cid) or {}
            aw = state["await"]

            # NAME
            if aw == "U_NAME_INPUT":
                new_name = raw.strip().title()[:120]
                old_name = prof.get("name") or ""
                warn = "⚠️ Duplicate name exists.\n\n" if _dup_by_name(new_name, exclude_cid=cid) else ""
                state["buffer"]["PENDING_NAME"] = new_name
                return send_whatsapp_buttons(
                    wa,
                    f"{warn}Change *Name*:\n• From: {old_name or '—'}\n• To:   {new_name}\n\nSave?",
                    [
                        {"id": "ADMIN_SAVE_NAME",    "title": "✅ Save"},
                        {"id": "ADMIN_EDIT_AGAIN",   "title": "↩️ Edit"},
                        {"id": "ADMIN_CANCEL_EDIT",  "title": "❌ Cancel"},
                    ]
                )

            # PHONE
            if aw == "U_PHONE_INPUT":
                norm = normalize_wa(raw)
                if not norm.startswith("+27"):
                    return _ask_text_prompt(wa, "Edit Phone", "Not SA format. Send 0…, 27…, or +27….")
                old_phone = prof.get("wa_number") or ""
                warn = "⚠️ Another client uses this number.\n\n" if _dup_by_phone(norm, exclude_cid=cid) else ""
                state["buffer"]["PENDING_PHONE"] = norm
                return send_whatsapp_buttons(
                    wa,
                    f"{warn}Change *Phone*:\n• From: {old_phone or '—'}\n• To:   {norm}\n\nSave?",
                    [
                        {"id": "ADMIN_SAVE_PHONE",   "title": "✅ Save"},
                        {"id": "ADMIN_EDIT_AGAIN",   "title": "↩️ Edit"},
                        {"id": "ADMIN_CANCEL_EDIT",  "title": "❌ Cancel"},
                    ]
                )

            # DOB
            if aw == "U_DOB_INPUT":
                m = re.fullmatch(r"\s*(\d{1,2})\s+([A-Za-z]{3,})\s*", raw.strip())
                if not m:
                    return _ask_text_prompt(wa, "Edit DOB", "Format *DD MON* (e.g., 21 MAY).")
                day_s, mon_s = m.group(1), m.group(2)
                mon_i = _month_to_int(mon_s)
                if mon_i is None:
                    return _ask_text_prompt(wa, "Edit DOB", "Month must be JAN, FEB, …")
                bday_old = f"{(prof.get('birthday_day') or '')}-{(prof.get('birthday_month') or '')}".strip("-") or "—"
                bday_new = f"{int(day_s)}-{mon_i}"
                state["buffer"]["PENDING_DOB"] = (int(day_s), int(mon_i))
                return send_whatsapp_buttons(
                    wa,
                    f"Change *DOB*:\n• From: {bday_old}\n• To:   {bday_new}\n\nSave?",
                    [
                        {"id": "ADMIN_SAVE_DOB",     "title": "✅ Save"},
                        {"id": "ADMIN_EDIT_AGAIN",   "title": "↩️ Edit"},
                        {"id": "ADMIN_CANCEL_EDIT",  "title": "❌ Cancel"},
                    ]
                )

            # MEDICAL
            if aw in ("U_MEDICAL_APPEND", "U_MEDICAL_REPLACE"):
                new_note = raw.strip()[:500]
                mode = "append" if aw.endswith("APPEND") else "replace"
                current = (prof.get("medical_notes") or "")[:300]
                preview_new = (new_note[:300] + ("…" if len(new_note) > 300 else ""))
                state["buffer"]["PENDING_MEDICAL"] = {"text": new_note, "append": (mode == "append")}
                return send_whatsapp_buttons(
                    wa,
                    f"Change *Medical Notes* ({mode}):\n• Current (first 300): {current or '—'}\n• New (first 300): {preview_new or '—'}\n\nSave?",
                    [
                        {"id": "ADMIN_SAVE_MEDICAL", "title": "✅ Save"},
                        {"id": "ADMIN_EDIT_AGAIN",   "title": "↩️ Edit"},
                        {"id": "ADMIN_CANCEL_EDIT",  "title": "❌ Cancel"},
                    ]
                )

            # CREDITS custom
            if aw == "U_CREDITS_INPUT":
                m = re.fullmatch(r"\s*([+-]?\d+)\s*", raw)
                if not m:
                    return _ask_text_prompt(wa, "Adjust Credits", "Reply with +N or -N (e.g., +1, -2).")
                delta = int(m.group(1))
                prof = crud.get_client_profile(cid)
                old = prof.get("credits", 0)
                new = old + delta
                state["buffer"]["PENDING_CREDITS_DELTA"] = delta
                return send_whatsapp_buttons(
                    wa,
                    f"Change *Credits*:\n• From: {old}\n• To:   {new}\n\nApply?",
                    [
                        {"id": "ADMIN_SAVE_CREDITS", "title": "✅ Save"},
                        {"id": "ADMIN_EDIT_AGAIN",   "title": "↩️ Edit"},
                        {"id": "ADMIN_CANCEL_EDIT",  "title": "❌ Cancel"},
                    ]
                )

    # ── SAVE / EDIT AGAIN / CANCEL for diffs
    if up in ("ADMIN_EDIT_AGAIN", "ADMIN_CANCEL_EDIT", "ADMIN_SAVE_NAME", "ADMIN_SAVE_PHONE", "ADMIN_SAVE_DOB", "ADMIN_SAVE_MEDICAL", "ADMIN_SAVE_CREDITS"):
        if not state.get("cid"):
            return _client_picker(wa, "Update: pick client")
        cid = state["cid"]
        prof = crud.get_client_profile(cid) or {}

        if up == "ADMIN_EDIT_AGAIN":
            # Go back to the last awaited prompt type
            # If we reached diff stage, we had set await to an *_INPUT value originally.
            # We keep it unchanged so Nadine can retype the value.
            aw = state.get("await")
            if not aw:
                return _update_menu(wa, cid)
            # Re-show the right prompt:
            if aw == "U_NAME_INPUT":
                return _ask_text_prompt(wa, "Edit Name", f"Current: *{prof.get('name') or '—'}*\nReply with the *new full name*.")
            if aw == "U_PHONE_INPUT":
                return _ask_text_prompt(wa, "Edit Phone", f"Current: *{prof.get('wa_number') or '—'}*\nReply with the *new SA phone* (0…, 27…, or +27…).")
            if aw == "U_DOB_INPUT":
                bday = f"{(prof.get('birthday_day') or '')}-{(prof.get('birthday_month') or '')}".strip("-") or "—"
                return _ask_text_prompt(wa, "Edit DOB", f"Current: *{bday}*\nReply as *DD MON* (e.g., 21 MAY).")
            if aw in ("U_MEDICAL_APPEND", "U_MEDICAL_REPLACE"):
                mode = "append a new note" if aw.endswith("APPEND") else "replace notes"
                return _ask_text_prompt(wa, "Medical Notes", f"Reply with the text to *{mode}*.")
            if aw == "U_CREDITS_INPUT":
                return _ask_text_prompt(wa, "Adjust Credits", "Reply with +N or -N (e.g., +1, -2).")
            return _update_menu(wa, cid)

        if up == "ADMIN_CANCEL_EDIT":
            state["await"] = None
            state["buffer"].pop("PENDING_NAME", None)
            state["buffer"].pop("PENDING_PHONE", None)
            state["buffer"].pop("PENDING_DOB", None)
            state["buffer"].pop("PENDING_MEDICAL", None)
            state["buffer"].pop("PENDING_CREDITS_DELTA", None)
            return _update_menu(wa, cid)

        # SAVE branches with undo tracking:
        if up == "ADMIN_SAVE_NAME":
            new_name = state["buffer"].get("PENDING_NAME")
            if new_name is None:
                return _update_menu(wa, cid)
            old = prof.get("name")
            _save_name(cid, new_name)
            state["undo"] = {"field": "name", "cid": cid, "old": old}
            state["await"] = None
            state["buffer"].pop("PENDING_NAME", None)
            send_whatsapp_buttons(wa, f"✅ Name updated.\nUndo?", [
                {"id": "ADMIN_UNDO_LAST",   "title": "↩️ Undo"},
                {"id": "ADMIN_UPDATE_BACK", "title": "Back"},
            ])
            return

        if up == "ADMIN_SAVE_PHONE":
            new_phone = state["buffer"].get("PENDING_PHONE")
            if new_phone is None:
                return _update_menu(wa, cid)
            old = prof.get("wa_number")
            _save_phone(cid, new_phone)
            state["undo"] = {"field": "wa_number", "cid": cid, "old": old}
            state["await"] = None
            state["buffer"].pop("PENDING_PHONE", None)
            send_whatsapp_buttons(wa, f"✅ Phone updated.\nUndo?", [
                {"id": "ADMIN_UNDO_LAST",   "title": "↩️ Undo"},
                {"id": "ADMIN_UPDATE_BACK", "title": "Back"},
            ])
            return

        if up == "ADMIN_SAVE_DOB":
            tup = state["buffer"].get("PENDING_DOB")
            if not tup:
                return _update_menu(wa, cid)
            old = (prof.get("birthday_day"), prof.get("birthday_month"))
            d, m = tup
            _save_dob(cid, int(d), int(m))
            state["undo"] = {"field": "dob", "cid": cid, "old": old}
            state["await"] = None
            state["buffer"].pop("PENDING_DOB", None)
            send_whatsapp_buttons(wa, f"✅ DOB updated.\nUndo?", [
                {"id": "ADMIN_UNDO_LAST",   "title": "↩️ Undo"},
                {"id": "ADMIN_UPDATE_BACK", "title": "Back"},
            ])
            return

        if up == "ADMIN_SAVE_MEDICAL":
            obj = state["buffer"].get("PENDING_MEDICAL") or {}
            text_new = obj.get("text", "")
            append = obj.get("append", True)
            old_full = prof.get("medical_notes") or ""
            _save_medical(cid, text_new, append=append if text_new else False)
            state["undo"] = {"field": "medical_notes", "cid": cid, "old": old_full}
            state["await"] = None
            state["buffer"].pop("PENDING_MEDICAL", None)
            send_whatsapp_buttons(wa, f"✅ Medical notes updated.\nUndo?", [
                {"id": "ADMIN_UNDO_LAST",   "title": "↩️ Undo"},
                {"id": "ADMIN_UPDATE_BACK", "title": "Back"},
            ])
            return

        if up == "ADMIN_SAVE_CREDITS":
            delta = state["buffer"].get("PENDING_CREDITS_DELTA")
            if delta is None:
                return _update_menu(wa, cid)
            prof = crud.get_client_profile(cid)
            old = prof.get("credits", 0)
            _adjust_credits(cid, int(delta))
            state["undo"] = {"field": "credits", "cid": cid, "old": old}
            state["await"] = None
            state["buffer"].pop("PENDING_CREDITS_DELTA", None)
            new = old + int(delta)
            send_whatsapp_buttons(wa, f"✅ Credits updated: {old} → {new}\nUndo?", [
                {"id": "ADMIN_UNDO_LAST",   "title": "↩️ Undo"},
                {"id": "ADMIN_UPDATE_BACK", "title": "Back"},
            ])
            return

    # ──────────────────────────────────────────────────────────────────────
    # NLP fallback & strict template backups (unchanged behavior)
    # ──────────────────────────────────────────────────────────────────────
    low = raw.lower()
    if low in ("new", "update", "cancel", "view", "book"):
        # Map to the same interactive intents
        return handle_admin_action(wa, f"ADMIN_INTENT_{low.upper()}")

    # Try your NLP helpers if not in a wizard state
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
                return send_whatsapp_text(wa, "✅ Recurring booking stub (wire your weekly finder).")

    # Interactive day/slots (legacy list navigation kept)
    if raw.startswith("ADMIN_DAY_"):
        d = raw.replace("ADMIN_DAY_", "")
        try:
            slots = crud.list_slots_for_day(date.fromisoformat(d))
            rows = [{"id": f"ADMIN_SLOT_{r['id']}", "title": str(r["start_time"]), "description": f"seats {r['seats_left']}"} for r in slots]
            return send_whatsapp_list(wa, f"Slots {d}", "Pick a slot:", "ADMIN_MENU", rows or [{"id": "ADMIN_MENU", "title": "⬅️ Menu"}])
        except Exception as e:
            logging.exception(e)
            return _root_menu(wa)

    if raw.startswith("ADMIN_VIEW_"):
        cid_s = raw.replace("ADMIN_VIEW_", "")
        cid = int(cid_s) if cid_s.isdigit() else None
        prof = crud.get_client_profile(cid) if cid else None
        if not prof:
            return send_whatsapp_text(wa, "Client not found.")
        return send_whatsapp_text(wa, _profile_text(cid))

    # Strict templates backup (unchanged)
    _strict = _strict_templates_handler(wa, raw)
    if _strict is not None:
        return _strict

    # Default → root menu
    return _root_menu(wa)


# ──────────────────────────────────────────────────────────────────────────────
# Strict template backups (unchanged, grouped here)
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

def _resolve_single_client(sender: str, name: str, next_prefix: str | None = None):
    matches = crud.find_clients_by_name(name, limit=6)
    if not matches:
        send_whatsapp_text(sender, f"⚠️ No client matching “{name}”.")
        return None
    if len(matches) == 1 or not next_prefix:
        return matches[0]
    rows = [{"id": f"{next_prefix}{m['id']}", "title": m["name"][:24], "description": m["wa_number"]} for m in matches]
    send_whatsapp_list(sender, "Who do you mean?", "Pick a client:", "ADMIN_MENU", rows)
    return None

def _strict_templates_handler(sender: str, raw: str):
    up = raw.upper()

    # Menu/help shortcuts
    if up in ("ADMIN", "ADMIN_MENU"):
        return _root_menu(sender)
    if up in ("HELP", "ADMIN_HELP", "?"):
        return _show_template(sender, None)
    if up in ("SHOW CLIENTS", "LIST CLIENTS", "ADMIN_LIST_CLIENTS"):
        clients = crud.list_clients(limit=20)
        rows = [{"id": f"ADMIN_VIEW_{c['id']}", "title": c["name"][:24], "description": f"{c['wa_number']} • {c.get('credits',0)} cr"} for c in clients]
        return send_whatsapp_list(sender, "Clients", "Latest clients:", "ADMIN_MENU",
                                  rows or [{"id": "ADMIN_MENU", "title": "⬅️ Menu"}])
    if up in ("SHOW SLOTS", "LIST SLOTS", "ADMIN_LIST_SLOTS"):
        days = crud.list_days_with_open_slots(days=21, limit_days=10)
        rows = [{"id": f"ADMIN_DAY_{d['session_date']}", "title": str(d['session_date']), "description": f"{d['slots']} open"} for d in days]
        return send_whatsapp_list(sender, "Open Slots", "Choose a day:", "ADMIN_MENU",
                                  rows or [{"id": "ADMIN_MENU", "title": "⬅️ Menu"}])

    # 1) ADD CLIENT "Full Name" PHONE 0XXXXXXXXX
    m = re.fullmatch(r'\s*ADD\s+CLIENT\s+"(.+?)"\s+PHONE\s+([+\d][\d\s-]+)\s*', raw, flags=re.IGNORECASE)
    if m:
        name = m.group(1).strip()
        phone = re.sub(r"[\s-]+", "", m.group(2))
        summary = f"Add client:\n• Name: {name}\n• Phone: {phone}"
        token = _build_token("ADD_CLIENT", name=name, phone=phone)
        return send_whatsapp_buttons(sender, summary, [
            {"id": token, "title": "Confirm"},
            {"id": "ADMIN_ABORT", "title": "Cancel"},
        ])

    # 2) SET DOB "Full Name" DD MON
    m = re.fullmatch(r'\s*SET\s+DOB\s+"(.+?)"\s+(\d{1,2})\s+([A-Za-z]{3,})\s*', raw, flags=re.IGNORECASE)
    if m:
        name, day_s, mon_s = m.group(1).strip(), m.group(2), m.group(3)
        mon_i = _month_to_int(mon_s)
        if mon_i is None:
            return _show_template(sender, "Invalid month (use JAN, FEB, …).")
        client = _resolve_single_client(sender, name)
        if not client:
            return None
        summary = f"Set DOB:\n• Client: {client['name']}\n• DOB: {day_s} {mon_s.upper()}"
        token = _build_token("SET_DOB", cid=client["id"], day=day_s, mon=mon_i)
        return send_whatsapp_buttons(sender, summary, [
            {"id": token, "title": "Confirm"},
            {"id": "ADMIN_ABORT", "title": "Cancel"},
        ])

    # 3) ADD NOTE "Full Name" - free text
    m = re.fullmatch(r'\s*ADD\s+NOTE\s+"(.+?)"\s*-\s*(.+)\s*', raw, flags=re.IGNORECASE)
    if m:
        name, note = m.group(1).strip(), m.group(2).strip()
        client = _resolve_single_client(sender, name)
        if not client:
            return None
        summary = f"Add Note:\n• Client: {client['name']}\n• Note: {note}"
        token = _build_token("ADD_NOTE", cid=client["id"], note=note)
        return send_whatsapp_buttons(sender, summary, [
            {"id": token, "title": "Confirm"},
            {"id": "ADMIN_ABORT", "title": "Cancel"},
        ])

    # 4) CANCEL NEXT "Full Name"
    m = re.fullmatch(r'\s*CANCEL\s+NEXT\s+"(.+?)"\s*', raw, flags=re.IGNORECASE)
    if m:
        name = m.group(1).strip()
        client = _resolve_single_client(sender, name)
        if not client:
            return None
        summary = f"Cancel next session:\n• Client: {client['name']}"
        token = _build_token("CANCEL_NEXT", cid=client["id"])
        return send_whatsapp_buttons(sender, summary, [
            {"id": token, "title": "Confirm"},
            {"id": "ADMIN_ABORT", "title": "Cancel"},
        ])

    # 5) NOSHOW TODAY "Full Name"
    m = re.fullmatch(r'\s*NOSHOW\s+TODAY\s+"(.+?)"\s*', raw, flags=re.IGNORECASE)
    if m:
        name = m.group(1).strip()
        client = _resolve_single_client(sender, name)
        if not client:
            return None
        summary = f"No-show today:\n• Client: {client['name']}"
        token = _build_token("NOSHOW_TODAY", cid=client["id"])
        return send_whatsapp_buttons(sender, summary, [
            {"id": token, "title": "Confirm"},
            {"id": "ADMIN_ABORT", "title": "Cancel"},
        ])

    # 6) BOOK "Full Name" ON YYYY-MM-DD HH:MM
    m = re.fullmatch(r'\s*BOOK\s+"(.+?)"\s+ON\s+(\d{4}-\d{2}-\d{2})\s+([0-2]?\d:\d{2})\s*', raw, flags=re.IGNORECASE)
    if m:
        name, dstr, hhmm = m.group(1).strip(), m.group(2), m.group(3)
        client = _resolve_single_client(sender, name)
        if not client:
            return None
        summary = f"Book session:\n• Client: {client['name']}\n• When: {dstr} {hhmm}"
        token = _build_token("BOOK_DT", cid=client["id"], d=dstr, t=hhmm)
        return send_whatsapp_buttons(sender, summary, [
            {"id": token, "title": "Confirm"},
            {"id": "ADMIN_ABORT", "title": "Cancel"},
        ])

    # 7) VIEW "Full Name"
    m = re.fullmatch(r'\s*VIEW\s+"(.+?)"\s*', raw, flags=re.IGNORECASE)
    if m:
        name = m.group(1).strip()
        client = _resolve_single_client(sender, name)
        if not client:
            return None
        prof = crud.get_client_profile(client["id"])
        if not prof:
            return send_whatsapp_text(sender, "Client not found.")
        return send_whatsapp_text(sender, _profile_text(client["id"]))

    # Button confirmations for strict templates
    if raw.startswith("ADMIN_CONFIRM__"):
        action, args = _parse_token(raw)
        logging.info(f"[ADMIN CONFIRM] action={action} args={args}")
        try:
            if action == "ADD_CLIENT":
                res = crud.create_client(args["name"], args["phone"])
                if not res:
                    return send_whatsapp_text(sender, "⚠️ Could not add client.")
                prof = crud.get_client_profile(res["id"])
                return send_whatsapp_text(sender, "✅ *Client added*\n" + _profile_text(prof["id"]))

            if action == "SET_DOB":
                ok = crud.update_client_dob(int(args["cid"]), int(args["day"]), int(args["mon"]))
                return send_whatsapp_text(sender, "✅ DOB updated." if ok else "⚠️ Update failed.")

            if action == "ADD_NOTE":
                ok = crud.update_client_medical(int(args["cid"]), args["note"], append=True)
                return send_whatsapp_text(sender, "✅ Note added." if ok else "⚠️ Update failed.")

            if action == "CANCEL_NEXT":
                ok = crud.cancel_next_booking_for_client(int(args["cid"]))
                return send_whatsapp_text(sender, "✅ Next session cancelled. (Credit +1)") if ok else send_whatsapp_text(sender, "⚠️ No upcoming booking found.")

            if action == "NOSHOW_TODAY":
                ok = crud.mark_no_show_today(int(args["cid"]))
                return send_whatsapp_text(sender, "✅ No-show recorded.") if ok else send_whatsapp_text(sender, "⚠️ No booking found today.")

            if action == "BOOK_DT":
                sess = crud.find_session_by_date_time(date.fromisoformat(args["d"]), args["t"])
                if not sess:
                    return send_whatsapp_text(sender, "⚠️ No matching session found.")
                ok = crud.create_booking(sess["id"], int(args["cid"]), seats=1, status="confirmed")
                return send_whatsapp_text(sender, "✅ Booked.") if ok else send_whatsapp_text(sender, "⚠️ Could not book (full?).")

        except Exception as e:
            logging.exception(e)
            return send_whatsapp_text(sender, "⚠️ Error performing action.")

    if raw == "ADMIN_ABORT":
        return send_whatsapp_text(sender, "Cancelled.")

    # Not a strict-template input
    return None
