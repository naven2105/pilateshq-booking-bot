# onboarding.py
import logging
from typing import Dict
from sqlalchemy import text

from utils import send_whatsapp_list
from crud import get_or_create_client
from db import get_session
from config import NADINE_WA

# Simple in-memory state per WhatsApp number (fine for MVP)
ONB_STATE: Dict[str, Dict] = {}

def handle_onboarding(sender: str, action: str):
    """
    Entry for menus and onboarding/update actions.
    Actions: ROOT_MENU | ONB_START | GET_STARTED | UPDATE_DETAILS |
             ONB_MEDICAL | ONB_TIMES | ONB_TYPE | ONB_FREQ | ONB_SUBMIT
    """
    client = get_or_create_client(sender)
    is_existing = bool((client.get("name") or "").strip())

    if action in ("ROOT_MENU", "MAIN_MENU"):
        return _show_root_menu(sender, is_existing)

    if action in ("ONB_START", "GET_STARTED", "UPDATE_DETAILS"):
        return _start_or_resume(sender, is_update=(action == "UPDATE_DETAILS"))

    if action in ("ONB_MEDICAL", "ONB_TIMES", "ONB_TYPE", "ONB_FREQ", "ONB_SUBMIT"):
        return _onb_action(sender, action)

    # Fallback to menu
    return _show_root_menu(sender, is_existing)

def capture_onboarding_free_text(sender: str, raw_text: str):
    """
    Called when user types free text and is mid-onboarding.
    Saves the last requested field and returns to the stepper.
    """
    s = ONB_STATE.get(sender) or {}
    field = s.get("awaiting")
    if not field:
        return _start_or_resume(sender, is_update=s.get("is_update", False))

    value = (raw_text or "").strip()
    s[field] = value
    s["awaiting"] = None

    return send_whatsapp_list(
        sender,
        "Saved",
        f"✅ Saved your {field}.\n\nYou can submit or fill the next item.",
        "ONB_MENU",
        [
            {"id": "ONB_MEDICAL", "title": "🩺 Medical / Injuries"},
            {"id": "ONB_TIMES",   "title": "⏰ Preferred Times"},
            {"id": "ONB_TYPE",    "title": "🎯 Session Type"},
            {"id": "ONB_FREQ",    "title": "📆 Sessions / Week"},
            {"id": "ONB_SUBMIT",  "title": "✅ Submit"},
        ]
    )

# ---------- internal helpers ----------

def _show_root_menu(sender: str, is_existing: bool):
    body = (
        "Welcome to PilatesHQ.\n"
        "🎉 Opening Special: Group @ R180 until Jan\n"
        "🌐 https://pilateshq.co.za\n\nChoose an option:"
    )
    options = [{"id": "WELLNESS", "title": "💡 Wellness Tips"}]
    if is_existing:
        options.append({"id": "UPDATE_DETAILS", "title": "✏️ Update My Details"})
    else:
        options.append({"id": "ONB_START", "title": "📝 Get Started"})
    return send_whatsapp_list(sender, "PilatesHQ", body, "MAIN_MENU", options)

def _start_or_resume(sender: str, is_update: bool = False):
    ONB_STATE[sender] = ONB_STATE.get(sender, {
        "medical": None, "times": None, "type": None, "freq": None, "awaiting": None, "is_update": is_update
    })
    ONB_STATE[sender]["is_update"] = is_update

    header = "Update Details" if is_update else "Getting Started"
    body = ("Let’s capture a few quick details.\n"
            "Tap a section below, then reply with your answer.\n"
            "You can submit when done.")
    return send_whatsapp_list(
        sender, header, body, "ONB_MENU",
        [
            {"id": "ONB_MEDICAL", "title": "🩺 Medical / Injuries"},
            {"id": "ONB_TIMES",   "title": "⏰ Preferred Times"},
            {"id": "ONB_TYPE",    "title": "🎯 Session Type"},
            {"id": "ONB_FREQ",    "title": "📆 Sessions / Week"},
            {"id": "ONB_SUBMIT",  "title": "✅ Submit"},
        ]
    )

def _onb_action(sender: str, action_id: str):
    s = ONB_STATE.setdefault(sender, {"medical": None, "times": None, "type": None, "freq": None, "awaiting": None})

    if action_id == "ONB_MEDICAL":
        s["awaiting"] = "medical"
        prompt = "Please describe any injuries or medical conditions (e.g., lower back pain, recent surgery)."
        return send_whatsapp_list(sender, "Medical", prompt, "ONB_BACK", [{"id": "ONB_START", "title": "⬅️ Onboarding"}])

    if action_id == "ONB_TIMES":
        s["awaiting"] = "times"
        prompt = "What times suit you best? (e.g., Mon & Wed 7–9am; Sat morning)"
        return send_whatsapp_list(sender, "Preferred Times", prompt, "ONB_BACK", [{"id": "ONB_START", "title": "⬅️ Onboarding"}])

    if action_id == "ONB_TYPE":
        s["awaiting"] = "type"
        prompt = "Which sessions are you interested in? (Single / Duo / Group)"
        return send_whatsapp_list(sender, "Session Type", prompt, "ONB_BACK", [{"id": "ONB_START", "title": "⬅️ Onboarding"}])

    if action_id == "ONB_FREQ":
        s["awaiting"] = "freq"
        prompt = "How many sessions per week? (1x, 2x, or 3x)"
        return send_whatsapp_list(sender, "Sessions / Week", prompt, "ONB_BACK", [{"id": "ONB_START", "title": "⬅️ Onboarding"}])

    if action_id == "ONB_SUBMIT":
        s["awaiting"] = None
        return _confirm_and_save(sender)

def _confirm_and_save(sender: str):
    s = ONB_STATE.get(sender, {})
    medical = s.get("medical") or ""
    times   = s.get("times") or ""
    sess_t  = (s.get("type") or "").lower()
    freq    = (s.get("freq") or "").lower()

    # Map freq → plan
    plan = "1x"
    if "3" in freq: plan = "3x"
    elif "2" in freq: plan = "2x"
    elif "1" in freq or "4 per month" in freq: plan = "1x"

    # Persist to clients
    try:
        with get_session() as dbs:
            dbs.execute(
                text("""
                    UPDATE clients
                    SET medical_notes = :medical,
                        notes = :notes,
                        plan = :plan
                    WHERE wa_number = :wa
                """),
                {
                    "medical": medical[:500],
                    "notes": f"pref_times={times}; type={sess_t}"[:500],
                    "plan": plan,
                    "wa": sender,
                },
            )
            dbs.commit()
    except Exception:
        logging.exception("[ONB] DB update failed")

    # Notify Nadine
    summary = (
        "🆕 Client Details Submitted\n"
        f"From: {sender}\n"
        f"Medical: {medical or '-'}\n"
        f"Times: {times or '-'}\n"
        f"Type: {sess_t or '-'}\n"
        f"Frequency: {freq or '-'} (plan={plan})"
    )
    send_whatsapp_list(
        NADINE_WA, "Admin: New/Updated Client", summary, "ADMIN_MENU",
        [{"id": "MAIN_MENU", "title": "⬅️ Menu"}]
    )

    # Confirm to client
    client_msg = (
        "✅ Thanks! Your details were sent to Nadine.\n"
        "She’ll follow up to confirm your plan and schedule.\n"
        "Meanwhile, you can ask me for wellness tips anytime."
    )
    send_whatsapp_list(
        sender, "Submitted", client_msg, "AFTER_SUBMIT",
        [{"id": "WELLNESS", "title": "💡 Wellness Tips"}, {"id": "MAIN_MENU", "title": "⬅️ Menu"}]
    )

    ONB_STATE.pop(sender, None)
    return
