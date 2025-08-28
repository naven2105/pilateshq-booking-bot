# app/admin.py
import os
import re
import logging
from datetime import date

from .utils import send_whatsapp_list, send_whatsapp_text, send_whatsapp_buttons, normalize_wa
from .crud import (
    list_clients, find_clients_by_name, get_client_profile,
    list_days_with_open_slots, list_slots_for_day,
    find_session_by_date_time,
    create_client, update_client_dob, update_client_medical,
    create_booking, cancel_booking, cancel_next_booking_for_client, mark_no_show_today,
)

# ---------- Admin auth ----------
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

# ---------- Helpers ----------
def _menu(recipient: str):
    return send_whatsapp_list(recipient, "Admin", "Try natural commands or pick an action:", "ADMIN_MENU",
        [{"id":"ADMIN_LIST_CLIENTS","title":"👥 Clients"},
         {"id":"ADMIN_LIST_SLOTS","title":"📅 Open Slots"},
         {"id":"ADMIN_HELP","title":"❓ Help"}])

def _help(recipient: str):
    send_whatsapp_text(recipient,
        "🧭 Admin NLP examples:\n"
        "• Add new client Steven Gerrard with number 084 568 7940\n"
        "• Change Henry Paul date of birth to 21 May\n"
        "• Update Mary Joseph - recent knee injury\n"
        "• Cancel Harry Pillay next session\n"
        "• John Doe is no show today\n"
        "• Book Priya on 2025-09-03 08:00\n"
        "You can also type: show clients / show slots."
    )

def _confirm(sender: str, summary: str, payload_id: str):
    # payload_id is an action token we’ll handle on button press
    send_whatsapp_buttons(sender, f"Confirm?\n{summary}",
                          [{"id": f"ADMIN_CONFIRM__{payload_id}", "title": "Confirm"},
                           {"id": "ADMIN_ABORT", "title": "Cancel"}])

def _pick_client(sender: str, name: str, next_id_prefix: str):
    cands = find_clients_by_name(name, limit=5)
    if not cands:
        return send_whatsapp_text(sender, f"No client matching '{name}'.")
    if len(cands) == 1:
        # Fake a list reply path into next handler
        return handle_admin_action(sender, f"{next_id_prefix}{cands[0]['id']}")
    rows = [{"id": f"{next_id_prefix}{c['id']}", "title": c["name"][:24], "description": c["wa_number"]} for c in cands]
    return send_whatsapp_list(sender, "Who do you mean?", "Pick a client:", "ADMIN_MENU", rows)

def _safe_int(x):
    try: return int(x)
    except: return None

# ---------- Main entry ----------
def handle_admin_action(sender: str, action: str):
    if not _is_admin(sender):
        return send_whatsapp_text(sender, "⛔ Only Nadine (admin) can perform admin functions.")

    up = (action or "").strip()
    upU = up.upper()
    logging.info(f"[ADMIN] '{up}'")

    # --- Confirm / abort buttons ---
    if upU.startswith("ADMIN_CONFIRM__"):
        token = up.split("__", 1)[1]
        return _handle_confirmation(sender, token)
    if upU == "ADMIN_ABORT":
        return send_whatsapp_text(sender, "Cancelled.")

    # --- Quick menus ---
    if upU in ("ADMIN", "ADMIN_MENU"): return _menu(sender)
    if upU in ("HELP", "ADMIN_HELP", "?"): return _help(sender)

    if upU == "ADMIN_LIST_CLIENTS":
        clients = list_clients(limit=20)
        rows = [{"id": f"ADMIN_VIEW_{c['id']}", "title": c["name"][:24], "description": c["wa_number"]} for c in clients]
        return send_whatsapp_list(sender, "Clients", "Latest clients:", "ADMIN_MENU",
                                  rows or [{"id": "ADMIN_MENU", "title": "⬅️ Menu"}])

    if upU == "ADMIN_LIST_SLOTS":
        days = list_days_with_open_slots(days=21, limit_days=10)
        rows = [{"id": f"ADMIN_DAY_{d['session_date']}", "title": str(d['session_date']), "description": f"{d['slots']} open"}
                for d in days]
        return send_whatsapp_list(sender, "Open Slots", "Choose a day:", "ADMIN_MENU",
                                  rows or [{"id": "ADMIN_MENU", "title": "⬅️ Menu"}])

    if upU.startswith("ADMIN_DAY_"):
        try:
            d = upU.replace("ADMIN_DAY_", "")
            slots = list_slots_for_day(date.fromisoformat(d))
            rows = [{"id": f"ADMIN_SLOT_{r['id']}", "title": str(r["start_time"]), "description": f"seats {r['seats_left']}"} for r in slots]
            return send_whatsapp_list(sender, f"Slots {d}", "Pick a slot:", "ADMIN_MENU",
                                      rows or [{"id": "ADMIN_MENU", "title": "⬅️ Menu"}])
        except Exception as e:
            logging.exception(e)
            return _menu(sender)

    if upU.startswith("ADMIN_VIEW_"):
        cid = _safe_int(upU.replace("ADMIN_VIEW_", ""))
        prof = get_client_profile(cid) if cid else None
        if not prof:
            return send_whatsapp_text(sender, "Client not found.")
        bday = f"{(prof.get('birthday_day') or '')}-{(prof.get('birthday_month') or '')}".strip("-")
        text = (f"👤 {prof['name']}\n"
                f"📱 {prof['wa_number']}\n"
                f"📅 Plan: {prof.get('plan','')}\n"
                f"🎂 DOB: {bday or '—'}\n"
                f"📝 Notes: {prof.get('medical_notes') or '—'}")
        return send_whatsapp_text(sender, text)

    # --- NLP: Add new client ---
    m = re.match(r'(?i)^\s*add\s+(?:new\s+)?client\s+(.+?)\s+(?:with\s+)?number\s+([+\d\s-]+)\s*$', up)
    if m:
        name = m.group(1).strip()
        number = re.sub(r'[\s-]+', '', m.group(2))
        res = create_client(name, number)
        return send_whatsapp_text(sender, f"✅ Added {res['name']} ({res['wa_number']}).") if res \
               else send_whatsapp_text(sender, "⚠️ Could not add client.")

    # --- NLP: Change DOB ---
    m = re.match(r'(?i)^\s*change\s+(.+?)\s+date\s+of\s+birth\s+to\s+(\d{1,2})\s+([A-Za-z]+)\s*$', up)
    if m:
        name, day_s, mon = m.group(1).strip(), int(m.group(2)), m.group(3).lower()
        mon_map = {"jan":1,"january":1,"feb":2,"february":2,"mar":3,"march":3,"apr":4,"april":4,"may":5,
                   "jun":6,"june":6,"jul":7,"july":7,"aug":8,"august":8,"sep":9,"sept":9,"september":9,
                   "oct":10,"october":10,"nov":11,"november":11,"dec":12,"december":12}
        month = mon_map.get(mon)
        if not month:
            return send_whatsapp_text(sender, "Could not parse month.")
        return _pick_client(sender, name, f"ADMIN_SET_DOB_{day_s}_{month}_")

    if upU.startswith("ADMIN_SET_DOB_"):
        # ADMIN_SET_DOB_<day>_<month>_<clientId>
        parts = upU.split("_")
        if len(parts) >= 5:
            day = _safe_int(parts[3]); month = _safe_int(parts[4]); cid = _safe_int(parts[5]) if len(parts) > 5 else None
            if cid is not None:
                ok = update_client_dob(cid, day, month)
                return send_whatsapp_text(sender, "✅ DOB updated." if ok else "⚠️ Update failed.")
        return send_whatsapp_text(sender, "⚠️ Could not update DOB.")

    # --- NLP: Update medical notes ---
    m = re.match(r'(?i)^\s*update\s+(.+?)\s*-\s*(.+)\s*$', up)
    if m:
        name, note = m.group(1).strip(), m.group(2).strip()
        return _pick_client(sender, name, f"ADMIN_SET_MED_{note}__")

    if up.startswith("ADMIN_SET_MED_"):
        # ADMIN_SET_MED_<note>__<clientId>
        try:
            _, payload = up.split("ADMIN_SET_MED_", 1)
            note, cid_s = payload.rsplit("__", 1)
            cid = _safe_int(cid_s)
            if not cid:
                return send_whatsapp_text(sender, "⚠️ Could not parse client.")
            ok = update_client_medical(cid, note, append=True)
            return send_whatsapp_text(sender, "✅ Notes updated." if ok else "⚠️ Update failed.")
        except Exception:
            return send_whatsapp_text(sender, "⚠️ Error updating notes.")

    # --- NLP: Cancel next session ---
    m = re.match(r'(?i)^\s*cancel\s+(.+?)\s+next\s+session\s*$', up)
    if m:
        name = m.group(1).strip()
        return _pick_client(sender, name, "ADMIN_CANCEL_NEXT_")

    if upU.startswith("ADMIN_CANCEL_NEXT_"):
        cid = _safe_int(upU.replace("ADMIN_CANCEL_NEXT_", ""))
        ok = cancel_next_booking_for_client(cid) if cid else False
        return send_whatsapp_text(sender, "✅ Next session cancelled." if ok else "⚠️ No upcoming booking found.")

    # --- NLP: No-show today ---
    m = re.match(r'(?i)^\s*(.+?)\s+is\s+no\s+show\s+today\.?\s*$', up)
    if m:
        name = m.group(1).strip()
        return _pick_client(sender, name, "ADMIN_NOSHOW_TODAY_")

    if upU.startswith("ADMIN_NOSHOW_TODAY_"):
        cid = _safe_int(upU.replace("ADMIN_NOSHOW_TODAY_", ""))
        ok = mark_no_show_today(cid) if cid else False
        return send_whatsapp_text(sender, "✅ No-show recorded." if ok else "⚠️ No booking found today.")

    # --- NLP: Book on YYYY-MM-DD HH:MM ---
    m = re.match(r'(?i)^\s*book\s+(.+?)\s+on\s+(\d{4}-\d{2}-\d{2})\s+([0-2]?\d:\d{2})\s*$', up)
    if m:
        name, dstr, hhmm = m.group(1).strip(), m.group(2), m.group(3)
        return _pick_client(sender, name, f"ADMIN_BOOK_DT_{dstr}_{hhmm}_")

    if upU.startswith("ADMIN_BOOK_DT_"):
        # ADMIN_BOOK_DT_<date>_<time>_<clientId>
        try:
            _, payload = up.split("ADMIN_BOOK_DT_", 1)
            dstr, hhmm, cid_s = payload.split("_", 2)
            cid = _safe_int(cid_s)
            sess = find_session_by_date_time(date.fromisoformat(dstr), hhmm)
            if not sess:
                return send_whatsapp_text(sender, "No matching session found.")
            ok = create_booking(sess["id"], cid, seats=1, status="confirmed")
            return send_whatsapp_text(sender, "✅ Booked." if ok else "⚠️ Could not book (full?).")
        except Exception as e:
            logging.exception(e)
            return send_whatsapp_text(sender, "⚠️ Error booking.")

    # --- Interactive picks from lists ---
    if upU.startswith("ADMIN_SLOT_"):
        # Could add: after selecting a slot, prompt to pick a client, etc.
        return send_whatsapp_text(sender, "Slot selected. Now type: Book <client name> on <YYYY-MM-DD HH:MM>")

    # Fallback
    _help(sender)
    return _menu(sender)


def _handle_confirmation(sender: str, token: str):
    # Placeholder if you later want multi-step confirms with payloads.
    # For Phase 1, we execute actions inline above, so nothing here.
    return send_whatsapp_text(sender, "Confirmed.")
