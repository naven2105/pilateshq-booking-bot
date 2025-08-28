# app/admin.py
import os
import re
import logging
from datetime import date
from urllib.parse import quote, unquote

from .utils import (
    send_whatsapp_list,
    send_whatsapp_text,
    send_whatsapp_buttons,
    normalize_wa,
)
from .crud import (
    list_clients,
    find_clients_by_name,
    get_client_profile,
    list_days_with_open_slots,
    list_slots_for_day,
    find_session_by_date_time,
    create_client,
    update_client_dob,
    update_client_medical,
    create_booking,
    cancel_next_booking_for_client,
    mark_no_show_today,
)

# ---------------- Admin auth ----------------
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


# ---------------- Strict template help ----------------
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


# ---------------- Utility: token encode/decode for confirms ----------------
def _build_token(action: str, **kwargs) -> str:
    # ADMIN_CONFIRM__ACTION|k1=v1|k2=v2…  (values URL-quoted)
    parts = [action.upper()]
    for k, v in kwargs.items():
        parts.append(f"{k}={quote(str(v))}")
    return "ADMIN_CONFIRM__" + "|".join(parts)

def _parse_token(payload: str) -> tuple[str, dict]:
    # payload like "ADMIN_CONFIRM__ACTION|k=v|k2=v2"
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


# ---------------- Helpers ----------------
def _menu(recipient: str):
    return send_whatsapp_list(
        recipient, "Admin", "Pick an action or type a command (exact):", "ADMIN_MENU",
        [
            {"id": "ADMIN_LIST_CLIENTS", "title": "👥 Clients"},
            {"id": "ADMIN_LIST_SLOTS",   "title": "📅 Open Slots"},
            {"id": "ADMIN_HELP",         "title": "❓ Help"},
        ],
    )

def _resolve_single_client(sender: str, name: str, next_prefix: str | None = None):
    """Find one client by name. If ambiguous, show a picker. Return dict row or None (when picker sent)."""
    matches = find_clients_by_name(name, limit=6)
    if not matches:
        send_whatsapp_text(sender, f"⚠️ No client matching “{name}”.")
        return None
    if len(matches) == 1 or not next_prefix:
        return matches[0]
    rows = [
        {"id": f"{next_prefix}{m['id']}", "title": m["name"][:24], "description": m["wa_number"]}
        for m in matches
    ]
    send_whatsapp_list(sender, "Who do you mean?", "Pick a client:", "ADMIN_MENU", rows)
    return None

def _month_to_int(mon: str) -> int | None:
    mon = mon.strip().lower()
    table = {
        "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
        "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
        "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10,
        "nov": 11, "november": 11, "dec": 12, "december": 12
    }
    return table.get(mon)


# ---------------- Entry point ----------------
def handle_admin_action(sender: str, text: str):
    if not _is_admin(sender):
        return send_whatsapp_text(sender, "⛔ Only Nadine (admin) can perform admin functions.")

    raw = (text or "").strip()
    up = raw.upper()
    logging.info(f"[ADMIN CMD] '{raw}'")

    # Basic menu/help shortcuts
    if up in ("ADMIN", "ADMIN_MENU"):
        return _menu(sender)
    if up in ("HELP", "ADMIN_HELP", "?"):
        return _show_template(sender, None)
    if up in ("SHOW CLIENTS", "LIST CLIENTS", "ADMIN_LIST_CLIENTS"):
        clients = list_clients(limit=20)
        rows = [{"id": f"ADMIN_VIEW_{c['id']}", "title": c["name"][:24], "description": c["wa_number"]} for c in clients]
        return send_whatsapp_list(sender, "Clients", "Latest clients:", "ADMIN_MENU",
                                  rows or [{"id": "ADMIN_MENU", "title": "⬅️ Menu"}])
    if up in ("SHOW SLOTS", "LIST SLOTS", "ADMIN_LIST_SLOTS"):
        days = list_days_with_open_slots(days=21, limit_days=10)
        rows = [{"id": f"ADMIN_DAY_{d['session_date']}", "title": str(d['session_date']), "description": f"{d['slots']} open"}
                for d in days]
        return send_whatsapp_list(sender, "Open Slots", "Choose a day:", "ADMIN_MENU",
                                  rows or [{"id": "ADMIN_MENU", "title": "⬅️ Menu"}])

    # -------- Strict templates (regex) --------
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
            return  # picker sent
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
            return
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
            return
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
            return
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
            return
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
            return
        prof = get_client_profile(client["id"])
        if not prof:
            return send_whatsapp_text(sender, "Client not found.")
        bday = f"{(prof.get('birthday_day') or '')}-{(prof.get('birthday_month') or '')}".strip("-")
        text = (f"👤 {prof['name']}\n"
                f"📱 {prof['wa_number']}\n"
                f"📅 Plan: {prof.get('plan','')}\n"
                f"🎂 DOB: {bday or '—'}\n"
                f"📝 Notes: {prof.get('medical_notes') or '—'}")
        return send_whatsapp_text(sender, text)

    # -------- Interactive follow-ons (from pickers/buttons) --------
    if raw.startswith("ADMIN_DAY_"):
        d = raw.replace("ADMIN_DAY_", "")
        try:
            slots = list_slots_for_day(date.fromisoformat(d))
            rows = [{"id": f"ADMIN_SLOT_{r['id']}", "title": str(r["start_time"]), "description": f"seats {r['seats_left']}"} for r in slots]
            return send_whatsapp_list(sender, f"Slots {d}", "Pick a slot:", "ADMIN_MENU", rows or [{"id": "ADMIN_MENU", "title": "⬅️ Menu"}])
        except Exception as e:
            logging.exception(e)
            return _menu(sender)

    if raw.startswith("ADMIN_VIEW_"):
        cid = int(raw.replace("ADMIN_VIEW_", "")) if raw.replace("ADMIN_VIEW_", "").isdigit() else None
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

    # Button confirmations
    if raw.startswith("ADMIN_CONFIRM__"):
        action, args = _parse_token(raw)
        logging.info(f"[ADMIN CONFIRM] action={action} args={args}")
        try:
            if action == "ADD_CLIENT":
                res = create_client(args["name"], args["phone"])
                return send_whatsapp_text(sender, f"✅ Added {res['name']} ({res['wa_number']}).") if res \
                    else send_whatsapp_text(sender, "⚠️ Could not add client.")
            if action == "SET_DOB":
                ok = update_client_dob(int(args["cid"]), int(args["day"]), int(args["mon"]))
                return send_whatsapp_text(sender, "✅ DOB updated." if ok else "⚠️ Update failed.")
            if action == "ADD_NOTE":
                ok = update_client_medical(int(args["cid"]), args["note"], append=True)
                return send_whatsapp_text(sender, "✅ Note added." if ok else "⚠️ Update failed.")
            if action == "CANCEL_NEXT":
                ok = cancel_next_booking_for_client(int(args["cid"]))
                return send_whatsapp_text(sender, "✅ Next session cancelled." if ok else "⚠️ No upcoming booking found.")
            if action == "NOSHOW_TODAY":
                ok = mark_no_show_today(int(args["cid"]))
                return send_whatsapp_text(sender, "✅ No-show recorded." if ok else "⚠️ No booking found today.")
            if action == "BOOK_DT":
                sess = find_session_by_date_time(date.fromisoformat(args["d"]), args["t"])
                if not sess:
                    return send_whatsapp_text(sender, "⚠️ No matching session found.")
                ok = create_booking(sess["id"], int(args["cid"]), seats=1, status="confirmed")
                return send_whatsapp_text(sender, "✅ Booked." if ok else "⚠️ Could not book (full?).")
        except Exception as e:
            logging.exception(e)
            return send_whatsapp_text(sender, "⚠️ Error performing action.")

    if raw == "ADMIN_ABORT":
        return send_whatsapp_text(sender, "Cancelled.")

    # If we reached here, input is non-conforming: show template
    return _show_template(sender, "Command not recognized. Please use the exact templates above.")
