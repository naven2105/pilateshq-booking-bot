import logging
from .config import NADINE_WA
from .utils import send_whatsapp_list, normalize_wa
from .crud import release_slot

def is_nadine(wa_from: str) -> bool:
    return normalize_wa(wa_from) == NADINE_WA

def handle_admin_action(sender: str, action: str):
    if not is_nadine(sender):
        # ignore silently or show menu
        send_whatsapp_list(sender, "Admin", "Only Nadine can perform admin actions.", "ADMIN_MENU",
                           [{"id": "MAIN_MENU", "title": "⬅️ Menu"}])
        return

    if action.startswith("APPROVE_"):
        sid = _safe_int(action.replace("APPROVE_", ""))
        # Placeholder: booking confirmation flow lives here later.
        _notify_admin("✅ Approved hold", sid)
        return

    if action.startswith("RELEASE_"):
        sid = _safe_int(action.replace("RELEASE_", ""))
        if sid:
            release_slot(sid, 1)
        _notify_admin("🔓 Released hold", sid)
        return

    # default
    send_whatsapp_list(NADINE_WA, "Admin", "Choose an action:", "ADMIN_MENU",
                       [{"id": "MAIN_MENU", "title": "⬅️ Menu"}])

def _notify_admin(msg: str, sid: int | None):
    body = f"{msg} | Session {sid}" if sid else msg
    send_whatsapp_list(NADINE_WA, "Admin", body, "ADMIN_MENU",
                       [{"id": "MAIN_MENU", "title": "⬅️ Menu"}])

def _safe_int(s: str):
    try:
        return int(s)
    except Exception:
        return None
