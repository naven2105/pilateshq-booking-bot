# router.py
from utils import send_whatsapp_list, normalize_wa
from onboarding import handle_onboarding, capture_onboarding_free_text
from admin import handle_admin_action
from wellness import handle_wellness_message

def route_message(message: dict):
    sender = normalize_wa(message["from"])
    mtype  = message.get("type", "")
    raw = ""

    if mtype == "interactive":
        inter = message["interactive"]
        if "button_reply" in inter:
            raw = inter["button_reply"]["id"]
        elif "list_reply" in inter:
            raw = inter["list_reply"]["id"]
    elif mtype == "text":
        raw = (message.get("text", {}).get("body") or "").strip()

    upper = (raw or "").upper().strip()

    # Root / menu
    if upper in ("HI", "HELLO", "START", "MENU", "MAIN_MENU"):
        return handle_onboarding(sender, "ROOT_MENU")

    # Onboarding & updates (new/existing)
    if upper in ("ONB_START", "GET_STARTED", "UPDATE_DETAILS",
                 "ONB_MEDICAL", "ONB_TIMES", "ONB_TYPE", "ONB_FREQ", "ONB_SUBMIT"):
        return handle_onboarding(sender, upper)

    # If user is mid-onboarding and sends free text, capture it
    # (onboarding module manages in-memory state)
    if mtype == "text":
        return capture_onboarding_free_text(sender, raw)

    # Admin actions (Nadine only; admin.py checks permission)
    if upper.startswith(("APPROVE_", "RELEASE_")):
        return handle_admin_action(sender, upper)

    # Wellness always available
    if upper.startswith("WELLNESS"):
        return handle_wellness_message(upper, sender)

    # Fallback → root menu
    return handle_onboarding(sender, "ROOT_MENU")
