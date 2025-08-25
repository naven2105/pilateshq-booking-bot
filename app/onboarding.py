# app/onboarding.py
import logging
from typing import Dict
from sqlalchemy import text

from .utils import send_whatsapp_list, normalize_wa
from .crud import get_or_create_client
from .db import get_session
from .config import NADINE_WA

# Simple in-memory state per user for the intake flow (OK for MVP)
ONB_STATE: Dict[str, Dict] = {}

FIELDS = ["name", "medical", "times", "type", "freq"]  # capture order

def handle_onboarding(sender: str, action: str):
    """Entry for menus and onboarding/update actions."""
    wa = normalize_wa(sender).lstrip("+")  # DB stores without '+', adjust if needed
    client = get_or_create_client(wa)
    has_name = bool((client.get("name") or "").strip())
    is_existing = has_name

    if action in ("ROOT_MENU", "MAIN_MENU"):
        return _show_root_menu(wa, is_existing)

    if action in ("ONB_START", "GET_STARTED", "UPDATE_DETAILS"):
        # Start with 'name' only if it's empty; otherwise jump to medical
        return _start_or_resume(wa, is_update=(action == "UPDATE_DETAILS"), ask_name=not has_name)

    if action in ("ONB_NAME", "ONB_MEDICAL", "ONB_TIMES", "ONB_TYPE", "ONB_FREQ", "ONB_SUBMIT"):
        return _onb_action(wa, action)

    # Fallback
    return _show_root_menu(wa, is_existing)

def capture_onboarding_free_text(sender: str, raw_text: str):
    """Capture free-text answer for whichever field is currently awaited."""
    wa = normalize_wa(sender).lstrip("+")
    s = ONB_STATE.get(wa) or {}
    field = s.get("awaiting")
    if not field:
        # Not waiting → bounce to stepper
        return _start_or_resume(wa, is_update=s.get("is_update", False), ask_name=False)

    value = (raw_text or "").strip()
    # Light validation/normalization
    if field == "name":
        value = value.title()[:120]
        if len(value) < 2:
            return _ask_again(wa, "Name seems too short — please enter your full name.")
    elif field == "type":
        value_low = value.lower()
        if "group" in value_low: value = "group"
        elif "duo" in value_low: value = "duo"
        elif "single" in value_low or "private" in value_low: value = "single"
        else:
            return _ask_again(wa, "Please reply with: Single, Duo, or Group.")
    elif field == "freq":
        value_low = value.lower().replace("x", "")
        if "3" in value_low: value = "3x"
        elif "2" in value_low: value = "2x"
        elif "1" in value_low or "4 per" in value_low: value = "1x"
        else:
            return _ask_again(wa, "Please reply with 1x, 2x, or 3x per week.")

    s[field] = value
    s["awaiting"] = None
    ONB_STATE[wa] = s
    return _stepper_menu(wa, header="Saved", body=f"✅ Saved your {field}. You can submit or fill the next item.")

# ---------------- internal helpers ----------------

def _show_root_menu(wa: str, is_existing: bool):
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
    return send_whatsapp_list(wa, "PilatesHQ", body, "MAIN_MENU", options)

def _start_or_resume(wa: str, is_update: bool, ask_name: bool):
    # Ensure state exists
    s = ONB_STATE.get(wa) or {"name": None, "medical": None, "times": None, "type": None, "freq": None}
    s["is_update"] = is_update
    s.setdefault("awaiting", None)
    ONB_STATE[wa] = s

    if ask_name:
        s["awaiting"] = "name"
        return send_whatsapp_list(
            wa, "Your Name", "Please reply with your full name (for Nadine’s records).",
            "ONB_BACK", [{"id": "ONB_START", "title": "⬅️ Onboarding"}]
        )

    # Otherwise show the stepper menu
    hdr = "Update Details" if is_update else "Getting Started"
    return _stepper_menu(wa, header=hdr, body="Tap a section below, then reply with your answer. You can submit when done.")

def _stepper_menu(wa: str, header: str, body: str):
    return send_whatsapp_list(
        wa, header, body, "ONB_MENU",
        [
            {"id": "ONB_MEDICAL", "title": "🩺 Medical / Injuries"},
            {"id": "ONB_TIMES",   "title": "⏰ Preferred Times"},
            {"id": "ONB_TYPE",    "title": "🎯 Session Type"},
            {"id": "ONB_FREQ",    "title": "📆 Sessions / Week"},
            {"id": "ONB_SUBMIT",  "title": "✅ Submit"},
        ]
    )

def _onb_action(wa: str, action_id: str):
    s = ONB_STATE.setdefault(wa, {"name": None, "medical": None, "times": None, "type": None, "freq": None, "awaiting": None})

    if action_id == "ONB_NAME":
        s["awaiting"] = "name"
        return send_whatsapp_list(wa, "Your Name", "Please reply with your full name.", "ONB_BACK", [{"id": "ONB_START", "title": "⬅️ Onboarding"}])

    if action_id == "ONB_MEDICAL":
        s["awaiting"] = "medical"
        return send_whatsapp_list(wa, "Medical", "Any injuries or medical conditions we should note?", "ONB_BACK", [{"id": "ONB_START", "title": "⬅️ Onboarding"}])

    if action_id == "ONB_TIMES":
        s["awaiting"] = "times"
        return send_whatsapp_list(wa, "Preferred Times", "Which days/times suit you best? (e.g., Mon & Wed 7–9am; Sat morning)", "ONB_BACK", [{"id": "ONB_START", "title": "⬅️ Onboarding"}])

    if action_id == "ONB_TYPE":
        s["awaiting"] = "type"
        return send_whatsapp_list(wa, "Session Type", "Which sessions? Reply: Single, Duo, or Group.", "ONB_BACK", [{"id": "ONB_START", "title": "⬅️ Onboarding"}])

    if action_id == "ONB_FREQ":
        s["awaiting"] = "freq"
        return send_whatsapp_list(wa, "Sessions / Week", "How many per week? Reply: 1x, 2x, or 3x.", "ONB_BACK", [{"id": "ONB_START", "title": "⬅️ Onboarding"}])

    if action_id == "ONB_SUBMIT":
        s["awaiting"] = None
        return _confirm_and_save(wa)

def _confirm_and_save(wa: str):
    s = ONB_STATE.get(wa, {})
    name    = (s.get("name") or "").strip()
    medical = (s.get("medical") or "").strip()
    times   = (s.get("times") or "").strip()
    sess_t  = (s.get("type") or "").lower().strip()
    freq    = (s.get("freq") or "").lower().strip()

    # Plan mapping
    plan = "1x"
    if "3" in freq: plan = "3x"
    elif "2" in freq: plan = "2x"

    # Persist into clients
    try:
        with get_session() as dbs:
            # Update name if provided
            if name:
                dbs.execute(text("UPDATE clients SET name = :nm WHERE wa_number = :wa"),
                            {"nm": name[:120], "wa": wa})
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
                    "wa": wa,
                },
            )
            dbs.commit()
    except Exception:
        logging.exception("[ONB] DB update failed")

    # Notify Nadine (admin)
    summary = (
        "🆕 Client Details Submitted\n"
        f"From: +{wa}\n"
        f"Name: {name or '-'}\n"
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
        f"+{wa}", "Submitted", client_msg, "AFTER_SUBMIT",
        [{"id": "WELLNESS", "title": "💡 Wellness Tips"}, {"id": "MAIN_MENU", "title": "⬅️ Menu"}]
    )

    ONB_STATE.pop(wa, None)
    return

def _ask_again(wa: str, prompt: str):
    return send_whatsapp_list(
        f"+{wa}", "Try Again", prompt, "ONB_BACK",
        [{"id": "ONB_START", "title": "⬅️ Onboarding"}]
    )
