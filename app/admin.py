# app/admin.py
import logging
import os
from .utils import send_whatsapp_list, normalize_wa
from .crud import (
    list_clients,
    list_available_slots,
    hold_or_reserve_slot,
    release_slot,
)

# Support multiple admin numbers via ENV (bare 27… format, comma-separated)
ADMIN_WA_LIST = [
    n.strip() for n in os.getenv("ADMIN_WA_LIST", "").split(",") if n.strip()
]

def is_admin(sender: str) -> bool:
    wa = normalize_wa(sender)
    return wa in ADMIN_WA_LIST


def handle_admin_action(sender: str, action: str):
    """All admin flows are triggered here from router."""
    if not is_admin(sender):
        return send_whatsapp_list(
            sender, "Admin", "Only Nadine/admins can perform admin actions.",
            "ADMIN_MENU", [{"id": "MAIN_MENU", "title": "⬅️ Menu"}]
        )

    up = (action or "").strip().upper()

    # Bare 'ADMIN' or unknown → show menu
    if up == "ADMIN":
        return _menu(sender)

    # List clients
    if up.startswith("ADMIN_LIST_CLIENTS"):
        clients = list_clients(limit=10) or []
        if not clients:
            return send_whatsapp_list(sender, "Clients", "No clients found.", "ADMIN_MENU",
                                      [{"id": "MAIN_MENU", "title": "⬅️ Menu"}])
        rows = []
        for c in clients:
            title = f"{c['name'][:18]} ({c['plan']})"[:24]
            rows.append({"id": f"ADMIN_VIEW_{c['id']}", "title": title, "description": c["wa_number"]})
        return send_whatsapp_list(sender, "Clients (latest 10)", "Tap a client to view (coming soon).",
                                  "ADMIN_MENU", rows)

    # List open slots (next 14d)
    if up.startswith("ADMIN_LIST_SLOTS"):
        slots = list_available_slots(days=14, min_seats=1, limit=10) or []
        if not slots:
            return send_whatsapp_list(sender, "Open Slots", "No open slots in next 14 days.", "ADMIN_MENU",
                                      [{"id": "MAIN_MENU", "title": "⬅️ Menu"}])
        rows = []
        for s in slots:
            label = f"{s['session_date']} {str(s['start_time'])[:5]}".replace("-", "/")
            rows.append({"id": f"ADMIN_HOLD_{s['id']}", "title": label[:24], "description": f"Left: {s['seats_left']}"})
        return send_whatsapp_list(sender, "Open Slots", "Choose a slot to HOLD 1 seat.", "ADMIN_MENU", rows)

    # Hold seat
    if up.startswith("ADMIN_HOLD_"):
        sid = _safe_int(up.replace("ADMIN_HOLD_", ""))
        ok = bool(sid) and hold_or_reserve_slot(sid, 1)
        msg = "✅ Held 1 seat." if ok else "⚠️ Could not hold (maybe full)."
        return send_whatsapp_list(sender, "Hold Seat", f"{msg} (Session {sid})", "ADMIN_MENU",
                                  [{"id": "ADMIN_LIST_SLOTS", "title": "🔄 Refresh Slots"},
                                   {"id": "MAIN_MENU", "title": "⬅️ Menu"}])

    # Release seat
    if up.startswith("ADMIN_RELEASE_"):
        sid = _safe_int(up.replace("ADMIN_RELEASE_", ""))
        ok = bool(sid) and release_slot(sid, 1)
        msg = "🔓 Released 1 seat." if ok else "⚠️ Could not release."
        return send_whatsapp_list(sender, "Release Seat", f"{msg} (Session {sid})", "ADMIN_MENU",
                                  [{"id": "ADMIN_LIST_SLOTS", "title": "🔄 Refresh Slots"},
                                   {"id": "MAIN_MENU", "title": "⬅️ Menu"}])

    # Default → menu
    return _menu(sender)


def _menu(recipient: str):
    return send_whatsapp_list(
        recipient, "Admin", "Choose an action:", "ADMIN_MENU",
        [
            {"id": "ADMIN_LIST_CLIENTS", "title": "👥 Clients"},
            {"id": "ADMIN_LIST_SLOTS", "title": "📅 Open Slots"},
            {"id": "MAIN_MENU", "title": "⬅️ Menu"}
        ]
    )


def _safe_int(s: str) -> int | None:
    try:
        return int(s)
    except Exception:
        return None
