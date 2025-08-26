# --- replace/extend in app/admin.py ---
from .config import NADINE_WA
from .utils import send_whatsapp_list, normalize_wa
from .crud import release_slot, list_available_slots, hold_or_reserve_slot, list_clients

def is_nadine(wa_from: str) -> bool:
    return normalize_wa(wa_from).lstrip("+") == ("+" + NADINE_WA).lstrip("+")

def handle_admin_action(sender: str, action: str):
    if not is_nadine(sender):
        return send_whatsapp_list(sender, "Admin", "Only Nadine can perform admin actions.",
                                  "ADMIN_MENU", [{"id":"MAIN_MENU","title":"⬅️ Menu"}])

    up = (action or "").strip().upper()

    # 1) List latest clients
    if up.startswith("ADMIN_LIST_CLIENTS"):
        clients = list_clients(limit=10)
        if not clients:
            return send_whatsapp_list(NADINE_WA, "Clients", "No clients found.", "ADMIN_MENU",
                                      [{"id":"MAIN_MENU","title":"⬅️ Menu"}])
        rows = []
        for c in clients:
            title = f"{c['name'][:18]} ({c['plan']})"[:24]
            rows.append({"id": f"ADMIN_VIEW_{c['id']}", "title": title, "description": c["wa_number"]})
        return send_whatsapp_list(NADINE_WA, "Clients (latest 10)", "Tap a client to view (coming soon).",
                                  "ADMIN_MENU", rows)

    # 2) List open slots → selecting a row HOLDS 1 seat
    if up.startswith("ADMIN_LIST_SLOTS"):
        slots = list_available_slots(days=14, min_seats=1, limit=10)
        if not slots:
            return send_whatsapp_list(NADINE_WA, "Open Slots", "No open slots in next 14 days.", "ADMIN_MENU",
                                      [{"id":"MAIN_MENU","title":"⬅️ Menu"}])
        rows = []
        for s in slots:
            label = f"{s['session_date']} {str(s['start_time'])[:5]}".replace("-","/")  # keep ≤24 chars
            rows.append({"id": f"ADMIN_HOLD_{s['id']}", "title": label[:24],
                         "description": f"Seats left: {s['seats_left']}"})
        return send_whatsapp_list(NADINE_WA, "Open Slots", "Choose a slot to HOLD 1 seat.", "ADMIN_MENU", rows)

    # 3) Hold seat: ADMIN_HOLD_<id>
    if up.startswith("ADMIN_HOLD_"):
        sid = _safe_int(up.replace("ADMIN_HOLD_", ""))
        ok = bool(sid) and hold_or_reserve_slot(sid, 1)
        msg = "✅ Held 1 seat." if ok else "⚠️ Could not hold (maybe full)."
        return send_whatsapp_list(NADINE_WA, "Hold Seat", f"{msg} (Session {sid})", "ADMIN_MENU",
                                  [{"id":"ADMIN_LIST_SLOTS","title":"🔄 Refresh Slots"},
                                   {"id":"MAIN_MENU","title":"⬅️ Menu"}])

    # 4) Release seat: ADMIN_RELEASE_<id>
    if up.startswith("ADMIN_RELEASE_"):
        sid = _safe_int(up.replace("ADMIN_RELEASE_", ""))
        rel = release_slot(sid, 1) if sid else None
        msg = "🔓 Released 1 seat." if rel else "⚠️ Could not release."
        return send_whatsapp_list(NADINE_WA, "Release Seat", f"{msg} (Session {sid})", "ADMIN_MENU",
                                  [{"id":"ADMIN_LIST_SLOTS","title":"🔄 Refresh Slots"},
                                   {"id":"MAIN_MENU","title":"⬅️ Menu"}])

    # Default admin menu
    return send_whatsapp_list(NADINE_WA, "Admin", "Choose an action:", "ADMIN_MENU",
                              [{"id":"ADMIN_LIST_CLIENTS","title":"👥 Clients"},
                               {"id":"ADMIN_LIST_SLOTS","title":"📅 Open Slots"},
                               {"id":"MAIN_MENU","title":"⬅️ Menu"}])

def _safe_int(s: str):
    try: return int(s)
    except Exception: return None
