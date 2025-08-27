# app/admin.py
import os
import logging
from datetime import date

from .utils import send_whatsapp_list, send_whatsapp_text, normalize_wa
from .crud import (
    list_clients, list_days_with_open_slots, list_slots_for_day,
    create_booking, cancel_booking, list_bookings_for_session,
    create_recurring_from_slot, find_clients_by_name, create_client,
    update_client_dob, update_client_medical, get_next_booking_for_client,
    cancel_next_booking_for_client, mark_no_show_today, mark_off_sick_today,
    find_session_by_date_time, find_next_n_weekday_time
)
from .admin_nlp import parse_admin_command, parse_admin_client_command

# -----------------------------------------------------------------------------
# Admin auth
# -----------------------------------------------------------------------------
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

# -----------------------------------------------------------------------------
# Ephemeral admin state (per-admin)
# -----------------------------------------------------------------------------
ADMIN_STATE = {}  # key='27...' -> dict(step, client_id, type, day)

def _state(sender: str) -> dict:
    return ADMIN_STATE.setdefault(normalize_wa(sender), {})

def _clear_state(sender: str):
    ADMIN_STATE.pop(normalize_wa(sender), None)

def _safe_int(x):
    try: return int(x)
    except: return None

# -----------------------------------------------------------------------------
# Public entry
# -----------------------------------------------------------------------------
def handle_admin_action(sender: str, action: str):
    if not _is_admin(sender):
        return send_whatsapp_text(sender, "⛔ Only Nadine (admin) can perform admin functions.")

    up = (action or "").strip()
    upU = up.upper()
    logging.debug(f"[ADMIN ACTION] '{up}'")

    # ---------- NLP: Booking (existing) ----------
    if upU.startswith("BOOK "):
        cmd = parse_admin_command(up)
        if not cmd:
            return send_whatsapp_list(
                sender, "Book (NLP)",
                "Try:\n• book priya every tuesday 08h00\n• book raj on 2025-09-03 17:00",
                "ADMIN_MENU",
                [{"id": "ADMIN_BOOK", "title": "Use guided flow"}, {"id": "ADMIN_MENU", "title": "⬅️ Menu"}]
            )
        # find client
        cands = find_clients_by_name(cmd["name"], limit=3)
        if not cands:
            return send_whatsapp_text(sender, f"No client matching '{cmd['name']}'.")
        if len(cands) > 1:
            rows = [{"id": f"ADMIN_PICK_{c['id']}_{cmd['intent']}__{cmd.get('date','')}__{cmd.get('weekday','')}__{cmd.get('time','')}__{cmd.get('weeks','')}",
                     "title": c["name"][:24], "description": c["wa_number"]} for c in cands]
            return send_whatsapp_list(sender, "Who do you mean?", "Pick a client:", "ADMIN_MENU", rows)
        client = cands[0]
        return _nlp_execute_booking(sender, client["id"], cmd)

    if upU.startswith("ADMIN_PICK_"):
        try:
            # ADMIN_PICK_<cid>_<intent>__<date>__<weekday>__<time>__<weeks>
            head, cid, intent_and_more = up.split("_", 2)
            parts = intent_and_more.split("__")
            intent = parts[0]; date_s = parts[1] or None
            weekday = parts[2] or None; hhmm = parts[3] or None; weeks = parts[4] or None
            cmd = {"intent": intent}
            if date_s:  cmd["date"] = date_s
            if weekday: cmd["weekday"] = int(weekday)
            if hhmm:    cmd["time"] = hhmm
            if weeks:   cmd["weeks"] = int(weeks)
            return _nlp_execute_booking(sender, _safe_int(cid), cmd)
        except Exception as e:
            logging.exception(f"[ADMIN NLP PICK ERR] {e}")
            return _menu(sender)

    # ---------- NLP: Client management (NEW) ----------
    client_cmd = parse_admin_client_command(up)
    if client_cmd:
        intent = client_cmd["intent"]
        name = client_cmd.get("name", "")

        # Helper to pick a single client or ask
        def pick_one(_name: str):
            cands = find_clients_by_name(_name, limit=3)
            if not cands:
                send_whatsapp_text(sender, f"No client matching '{_name}'.")
                return None
            if len(cands) > 1:
                rows = [{"id": f"ADMIN_EDIT_PICK_{c['id']}__{intent}__{client_cmd.get('day','')}__{client_cmd.get('month','')}__{client_cmd.get('note','')}",
                         "title": c["name"][:24], "description": c["wa_number"]} for c in cands]
                send_whatsapp_list(sender, "Who do you mean?", "Pick a client:", "ADMIN_MENU", rows)
                return None
            return cands[0]["id"]

        # Add client
        if intent == "add_client":
            res = create_client(name=client_cmd["name"], wa_number=client_cmd["number"])
            return send_whatsapp_text(sender, f"✅ Added client {res['name']} ({res['wa_number']}).") if res else \
                   send_whatsapp_text(sender, "⚠️ Could not add client.")

        # Update DOB
        if intent == "update_dob":
            cid = pick_one(name)
            if cid is None: return  # selection list sent if ambiguous
            ok = update_client_dob(cid, client_cmd["day"], client_cmd["month"])
            return send_whatsapp_text(sender, "✅ DOB updated.") if ok else send_whatsapp_text(sender, "⚠️ Update failed.")

        # Update medical notes (append)
        if intent == "update_medical":
            cid = pick_one(name)
            if cid is None: return
            ok = update_client_medical(cid, client_cmd["note"], append=True)
            return send_whatsapp_text(sender, "✅ Notes updated.") if ok else send_whatsapp_text(sender, "⚠️ Update failed.")

        # Cancel next session
        if intent == "cancel_next":
            cid = pick_one(name)
            if cid is None: return
            ok = cancel_next_booking_for_client(cid)
            return send_whatsapp_text(sender, "✅ Next session cancelled.") if ok else send_whatsapp_text(sender, "⚠️ No upcoming booking found.")

        # Off sick today (cancel all today's bookings)
        if intent == "off_sick_today":
            cid = pick_one(name)
            if cid is None: return
            n = mark_off_sick_today(cid)
            return send_whatsapp_text(sender, f"✅ Marked off sick; cancelled {n} booking(s) today.") if n > 0 else \
                   send_whatsapp_text(sender, "⚠️ No booking to cancel today.")

        # No show today (first today booking → noshow; does not free seat)
        if intent == "no_show_today":
            cid = pick_one(name)
            if cid is None: return
            ok = mark_no_show_today(cid)
            return send_whatsapp_text(sender, "✅ No-show recorded for today.") if ok else send_whatsapp_text(sender, "⚠️ No booking found today.")

        # If we get here
        return send_whatsapp_text(sender, "⚠️ Could not parse that command.")

    # ---------- Guided admin menu ----------
    if upU in ("ADMIN", "ADMIN_MENU"):
        return _menu(sender)

    if upU == "ADMIN_LIST_CLIENTS":
        clients = list_clients(limit=10)
        rows = [{"id": f"ADMIN_VIEW_{c['id']}", "title": c["name"][:24], "description": c["wa_number"]} for c in clients]
        return send_whatsapp_list(sender, "Clients", "Latest clients:", "ADMIN_MENU",
                                  rows or [{"id":"ADMIN_MENU","title":"⬅️ Menu"}])

    if upU == "ADMIN_LIST_SLOTS":
        days = list_days_with_open_slots(days=21, limit_days=10)
        rows = [{"id": f"ADMIN_DAY_{d['session_date']}", "title": str(d["session_date"]), "description": f"{d['slots']} open"} for d in days]
        return send_whatsapp_list(sender, "Open Slots", "Choose a day:", "ADMIN_MENU",
                                  rows or [{"id":"ADMIN_MENU","title":"⬅️ Menu"}])

    if upU.startswith("ADMIN_DAY_"):
        day_str = upU.replace("ADMIN_DAY_", "")
        slots = list_slots_for_day(day=date.fromisoformat(day_str), limit=10)
        rows = [{"id": f"ADMIN_SLOT_{s['id']}", "title": str(s['start_time'])[:5], "description": f"Left: {s['seats_left']}"} for s in slots]
        return send_whatsapp_list(sender, f"Slots {day_str}", "Pick a slot:", "ADMIN_MENU",
                                  rows or [{"id":"ADMIN_MENU","title":"⬅️ Menu"}])

    # Guided booking flow
    if upU.startswith("ADMIN_BOOK"):
        st = _state(sender); st.clear(); st["step"]="pick_client"
        clients = list_clients(limit=10)
        rows = [{"id": f"ADMIN_BOOK_CLIENT_{c['id']}", "title": c["name"][:24], "description": c["wa_number"]} for c in clients]
        return send_whatsapp_list(sender, "Book → Pick Client", "Choose a client:", "ADMIN_MENU",
                                  rows or [{"id":"ADMIN_MENU","title":"⬅️ Menu"}])

    if upU.startswith("ADMIN_BOOK_CLIENT_"):
        cid = _safe_int(upU.replace("ADMIN_BOOK_CLIENT_", ""))
        st = _state(sender); st["client_id"]=cid; st["step"]="pick_type"
        return send_whatsapp_list(sender, "Book → Type", "Select session type:", "ADMIN_MENU",
                                  [{"id":"ADMIN_BOOK_TYPE_SINGLE","title":"Single"},
                                   {"id":"ADMIN_BOOK_TYPE_DUO","title":"Duo"},
                                   {"id":"ADMIN_BOOK_TYPE_GROUP","title":"Group"}])

    if upU.startswith("ADMIN_BOOK_TYPE_"):
        typ = upU.replace("ADMIN_BOOK_TYPE_", "").lower()
        st = _state(sender); st["type"]=typ; st["step"]="pick_day"
        days = list_days_with_open_slots(days=28, limit_days=10)
        rows = [{"id": f"ADMIN_BOOK_DAY_{d['session_date']}", "title": str(d["session_date"]), "description": f"{d['slots']} slots"} for d in days]
        return send_whatsapp_list(sender, "Book → Day", "Pick a day:", "ADMIN_MENU",
                                  rows or [{"id":"ADMIN_MENU","title":"⬅️ Menu"}])

    if upU.startswith("ADMIN_BOOK_DAY_"):
        day_str = upU.replace("ADMIN_BOOK_DAY_", "")
        st = _state(sender); st["day"]=day_str; st["step"]="pick_slot"
        slots = list_slots_for_day(day=date.fromisoformat(day_str), limit=10)
        rows = [{"id": f"ADMIN_BOOK_SLOT_{s['id']}", "title": str(s['start_time'])[:5], "description": f"Left: {s['seats_left']}"} for s in slots]
        return send_whatsapp_list(sender, "Book → Slot", "Pick a time:", "ADMIN_MENU",
                                  rows or [{"id":"ADMIN_MENU","title":"⬅️ Menu"}])

    if upU.startswith("ADMIN_BOOK_SLOT_"):
        sid = _safe_int(upU.replace("ADMIN_BOOK_SLOT_", ""))
        st = _state(sender); cid = st.get("client_id")
        if not (sid and cid):
            return send_whatsapp_list(sender, "Book", "Missing selection; please restart.", "ADMIN_MENU",
                                      [{"id":"ADMIN_BOOK","title":"🔁 Start Booking"}])
        ok = create_booking(sid, cid, seats=1, status="confirmed")
        if ok:
            return send_whatsapp_list(sender, "Booked ✔",
                f"Client #{cid} booked into session {sid}. Repeat weekly?",
                "ADMIN_MENU",
                [{"id": f"ADMIN_BOOK_RECUR_{sid}_4",  "title": "Every week ×4"},
                 {"id": f"ADMIN_BOOK_RECUR_{sid}_8",  "title": "Every week ×8"},
                 {"id": f"ADMIN_BOOK_RECUR_{sid}_12", "title": "Every week ×12"}])
        else:
            return send_whatsapp_list(sender, "Book", "⚠️ Slot unavailable; try another.", "ADMIN_MENU",
                                      [{"id":"ADMIN_BOOK","title":"🔁 Start Booking"}])

    if upU.startswith("ADMIN_BOOK_RECUR_"):
        parts = upU.split("_")
        sid = _safe_int(parts[3]) if len(parts) > 3 else None
        weeks = _safe_int(parts[4]) if len(parts) > 4 else 4
        st = _state(sender); cid = st.get("client_id")
        if not (sid and cid and weeks):
            return send_whatsapp_list(sender, "Repeat Weekly","Missing data; please re-start booking.",
                                      "ADMIN_MENU",[{"id":"ADMIN_BOOK","title":"🔁 Start Booking"}])
        res = create_recurring_from_slot(sid, cid, weeks=weeks, seats=1)
        _clear_state(sender)
        return send_whatsapp_list(sender, "Repeat Weekly",
                                  f"Created {res['created']} bookings; skipped {res['skipped']}.",
                                  "ADMIN_MENU",
                                  [{"id":"ADMIN_BOOK","title":"➕ Book Another"},
                                   {"id":"ADMIN_MENU","title":"⬅️ Menu"}])

    # Fallback
    return _menu(sender)

# ---------- Helpers ----------

def _menu(recipient: str):
    return send_whatsapp_list(recipient, "Admin", "Choose an action:", "ADMIN_MENU",
        [{"id":"ADMIN_BOOK","title":"➕ Book Client"},
         {"id":"ADMIN_LIST_CLIENTS","title":"👥 Clients"},
         {"id":"ADMIN_LIST_SLOTS","title":"📅 Open Slots"},
         {"id":"MAIN_MENU","title":"⬅️ Menu"}])

def _nlp_execute_booking(sender: str, client_id: int, cmd: dict):
    if not client_id:
        return send_whatsapp_text(sender, "Could not parse client; please try again.")
    intent = cmd.get("intent")
    if intent == "book_single":
        d = date.fromisoformat(cmd["date"]); hhmm = cmd["time"]
        sess = find_session_by_date_time(d, hhmm)
        if not sess:
            return send_whatsapp_list(sender, "Book (NLP)", "No matching session found.", "ADMIN_MENU",
                                      [{"id":"ADMIN_MENU","title":"⬅️ Menu"}])
        ok = create_booking(sess["id"], client_id, seats=1, status="confirmed")
        msg = "✅ Booked." if ok else "⚠️ Could not book (full?)."
        return send_whatsapp_list(sender, "Book (NLP)", f"{msg} {d} {hhmm}.", "ADMIN_MENU",
                                  [{"id":"ADMIN_MENU","title":"⬅️ Menu"}])
    if intent == "book_recurring":
        weekday = int(cmd["weekday"]); hhmm = cmd["time"]; weeks = int(cmd.get("weeks", 4))
        fut = find_next_n_weekday_time(weekday, hhmm, date.today(), weeks=weeks)
        made = skipped = 0
        for row in fut:
            if create_booking(row["id"], client_id, seats=1, status="confirmed"):
                made += 1
            else:
                skipped += 1
        return send_whatsapp_list(sender, "Book (NLP)", f"Done. Created {made}, skipped {skipped}.",
                                  "ADMIN_MENU",[{"id":"ADMIN_MENU","title":"⬅️ Menu"}])
    return send_whatsapp_text(sender, "Unsupported command.")
