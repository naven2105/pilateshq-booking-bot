# app/admin.py
import os
import logging
from datetime import date

from .utils import send_whatsapp_list, send_whatsapp_text, send_whatsapp_buttons, normalize_wa
from .crud import (
    list_clients, list_days_with_open_slots, list_slots_for_day,
    create_booking, create_recurring_from_slot, find_clients_by_name,
    create_client, update_client_dob, update_client_medical,
    cancel_next_booking_for_client, mark_no_show_today, mark_off_sick_today,
    find_session_by_date_time, find_next_n_weekday_time
)
from .admin_nlp import parse_admin_command, parse_admin_client_command

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

# in-memory per-admin state
ADMIN_STATE = {}  # key='+27...' -> dict(step, pending={kind:..., data:{...}}, ...)
def _state(sender: str) -> dict: return ADMIN_STATE.setdefault(normalize_wa(sender), {})
def _clear_state(sender: str): ADMIN_STATE.pop(normalize_wa(sender), None)
def _safe_int(x): 
    try: return int(x)
    except: return None

def _menu(recipient: str):
    return send_whatsapp_list(recipient, "Admin", "Try NLP or choose an action:", "ADMIN_MENU",
        [{"id":"ADMIN_BOOK","title":"➕ Book Client"},
         {"id":"ADMIN_LIST_CLIENTS","title":"👥 Clients"},
         {"id":"ADMIN_LIST_SLOTS","title":"📅 Open Slots"}])

def _help(recipient: str):
    send_whatsapp_text(recipient,
        "🧭 Admin NLP examples:\n"
        "• add new client Steven Gerrard with number 084 568 7940\n"
        "• change Henry Paul date of birth to 21 May\n"
        "• update Mary Joseph - recent knee injury\n"
        "• cancel Harry Pillay next session\n"
        "• Sarah Hopkins is off sick\n"
        "• John Doe is no show today\n"
        "• book Priya every tuesday 08h00\n"
        "• book Raj on 2025-09-03 17:00"
    )

def _confirm(sender: str, summary: str, pending: dict):
    st = _state(sender)
    st["pending"] = pending
    send_whatsapp_buttons(sender, f"Confirm?\n{summary}",
                          [{"id":"ADMIN_CONFIRM","title":"Confirm"},
                           {"id":"ADMIN_ABORT","title":"Cancel"}])

def handle_admin_action(sender: str, action: str):
    if not _is_admin(sender):
        return send_whatsapp_text(sender, "⛔ Only Nadine (admin) can perform admin functions.")
    up = (action or "").strip()
    upU = up.upper()
    logging.debug(f"[ADMIN ACTION] '{up}'")

    # confirmations
    if upU == "ADMIN_CONFIRM":
        st = _state(sender)
        p = st.get("pending")
        if not p:
            return send_whatsapp_text(sender, "Nothing to confirm.")
        kind = p.get("kind"); data = p.get("data", {})
        _state(sender).pop("pending", None)

        # Execute pending
        if kind == "update_dob":
            ok = update_client_dob(data["client_id"], data["day"], data["month"])
            return send_whatsapp_text(sender, "✅ DOB updated." if ok else "⚠️ Update failed.")
        if kind == "update_medical":
            ok = update_client_medical(data["client_id"], data["note"], append=True)
            return send_whatsapp_text(sender, "✅ Notes updated." if ok else "⚠️ Update failed.")
        if kind == "cancel_next":
            ok = cancel_next_booking_for_client(data["client_id"])
            return send_whatsapp_text(sender, "✅ Next session cancelled." if ok else "⚠️ No upcoming booking found.")
        if kind == "off_sick_today":
            n = mark_off_sick_today(data["client_id"])
            return send_whatsapp_text(sender, f"✅ Off-sick; cancelled {n} booking(s) today." if n>0 else "⚠️ No booking to cancel today.")
        if kind == "no_show_today":
            ok = mark_no_show_today(data["client_id"])
            return send_whatsapp_text(sender, "✅ No-show recorded." if ok else "⚠️ No booking found today.")
        return send_whatsapp_text(sender, "⚠️ Unknown pending action.")

    if upU == "ADMIN_ABORT":
        _state(sender).pop("pending", None)
        return send_whatsapp_text(sender, "Cancelled.")

    # help/menu shortcuts
    if upU in ("ADMIN", "ADMIN_MENU"): return _menu(sender)
    if upU in ("HELP","?","AIDE"): return _help(sender)

    # ---------- NLP: client management ----------
    client_cmd = parse_admin_client_command(up)
    if client_cmd:
        intent = client_cmd["intent"]; name = client_cmd.get("name","")

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

        # Add client executes immediately (non-destructive)
        if intent == "add_client":
            res = create_client(name=client_cmd["name"], wa_number=client_cmd["number"])
            return send_whatsapp_text(sender, f"✅ Added {res['name']} ({res['wa_number']}).") if res \
                   else send_whatsapp_text(sender, "⚠️ Could not add client.")

        # Destructive / sensitive actions → confirm
        if intent == "update_dob":
            cid = pick_one(name); 
            if cid is None: return
            _confirm(sender,
                     f"Update DOB for client #{cid} to {client_cmd['day']:02d}-{client_cmd['month']:02d}.",
                     {"kind":"update_dob","data":{"client_id":cid,"day":client_cmd["day"],"month":client_cmd["month"]}})
            return

        if intent == "update_medical":
            cid = pick_one(name); 
            if cid is None: return
            note_preview = (client_cmd["note"][:120] + ("…" if len(client_cmd["note"])>120 else ""))
            _confirm(sender,
                     f"Append medical note for client #{cid}:\n“{note_preview}”",
                     {"kind":"update_medical","data":{"client_id":cid,"note":client_cmd["note"]}})
            return

        if intent == "cancel_next":
            cid = pick_one(name); 
            if cid is None: return
            _confirm(sender,
                     f"Cancel NEXT session for client #{cid}.",
                     {"kind":"cancel_next","data":{"client_id":cid}})
            return

        if intent == "off_sick_today":
            cid = pick_one(name); 
            if cid is None: return
            _confirm(sender,
                     f"Mark OFF-SICK today and cancel today's bookings for client #{cid}.",
                     {"kind":"off_sick_today","data":{"client_id":cid}})
            return

        if intent == "no_show_today":
            cid = pick_one(name); 
            if cid is None: return
            _confirm(sender,
                     f"Mark NO-SHOW for today for client #{cid}. (seat not freed)",
                     {"kind":"no_show_today","data":{"client_id":cid}})
            return

    # ---------- NLP: booking (existing) ----------
    if upU.startswith("BOOK "):
        cmd = parse_admin_command(up)
        if not cmd:
            return _help(sender)
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
            _, cid, intent_and_more = up.split("_", 2)
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

    # ---------- Guided fallback (kept, minimal) ----------
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

    # fallback: show help + menu
    _help(sender)
    return _menu(sender)

def _nlp_execute_booking(sender: str, client_id: int, cmd: dict):
    if not client_id:
        return send_whatsapp_text(sender, "Could not parse client; please try again.")
    intent = cmd.get("intent")
    if intent == "book_single":
        d = date.fromisoformat(cmd["date"]); hhmm = cmd["time"]
        sess = find_session_by_date_time(d, hhmm)
        if not sess:
            return send_whatsapp_list(sender, "Book (NLP)", "No matching session found.", "ADMIN_MENU",
                                      [{"id":"ADMIN_LIST_SLOTS","title":"📅 Open Slots"}])
        ok = create_booking(sess["id"], client_id, seats=1, status="confirmed")
        msg = "✅ Booked." if ok else "⚠️ Could not book (full?)."
        return send_whatsapp_text(sender, f"{msg} {d} {hhmm}.")
    if intent == "book_recurring":
        weekday = int(cmd["weekday"]); hhmm = cmd["time"]; weeks = int(cmd.get("weeks", 4))
        fut = find_next_n_weekday_time(weekday, hhmm, date.today(), weeks=weeks)
        made = skipped = 0
        for row in fut:
            if create_booking(row["id"], client_id, seats=1, status="confirmed"): made += 1
            else: skipped += 1
        return send_whatsapp_text(sender, f"Done. Created {made}, skipped {skipped}.")
    return send_whatsapp_text(sender, "Unsupported booking command.")
