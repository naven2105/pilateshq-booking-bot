# app/admin.py
from .config import NADINE_WA
from ..utils import send_whatsapp_list, normalize_wa
from ..crud import release_slot

def is_nadine(wa_from: str) -> bool:
    return normalize_wa(wa_from).lstrip("+") == ("+" + NADINE_WA).lstrip("+")

def handle_admin_action(sender: str, action: str):
    if not is_nadine(sender):
        return send_whatsapp_list(sender, "Admin", "Only Nadine can perform admin actions.",
                                  "ADMIN_MENU", [{"id": "MAIN_MENU", "title": "⬅️ Menu"}])

    if action.startswith("APPROVE_"):
        sid = _safe_int(action.replace("APPROVE_", ""))
        return send_whatsapp_list(NADINE_WA, "Admin", f"✅ Approved hold | Session {sid}",
                                  "ADMIN_MENU", [{"id": "MAIN_MENU", "title": "⬅️ Menu"}])

    if action.startswith("RELEASE_"):
        sid = _safe_int(action.replace("RELEASE_", ""))
        if sid: release_slot(sid, 1)
        return send_whatsapp_list(NADINE_WA, "Admin", f"🔓 Released hold | Session {sid}",
                                  "ADMIN_MENU", [{"id": "MAIN_MENU", "title": "⬅️ Menu"}])

    return send_whatsapp_list(NADINE_WA, "Admin", "Choose an action:",
                              "ADMIN_MENU", [{"id": "MAIN_MENU", "title": "⬅️ Menu"}])

def _safe_int(s: str):
    try: return int(s)
    except Exception: return None
