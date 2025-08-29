import logging
from typing import Dict
from sqlalchemy import text

from .utils import send_whatsapp_list, normalize_wa
from .db import get_session
from . import crud  # module import to avoid name-level binding during import time
# If you don't have get_or_create_client yet, you can inline a simple version here.

# Minimal in-memory state for intake (MVP)
ONB_STATE: Dict[str, Dict] = {}   # key = wa (27...), value = {"awaiting": field, ...}

FIELDS = ["name", "medical", "times", "type", "freq"]  # order of capture


def handle_onboarding(sender: str, action: str | None = None):
    """
    Entry point from router.
    - sender: raw wa (may be +27… or 27…); normalize to 27…
    - action: None for "hello", or an interactive payload id
    """
    wa = normalize_wa(sender)  # "27XXXXXXXXX"
    # Ensure client row exists
    try:
        crud.get_or_create_client(wa)
    except Exception:
        logging.exception("[ONB] get_or_create_client failed")

    # First-time / menu
    if not action or action.upper() in ("ROOT_MENU", "MAIN_MENU"):
        return _show_root_menu(wa)

    up = action.upper()

    # Stepper entries
    if up in ("ONB_START", "UPDATE_DETAILS"):
        return _stepper_menu(wa, header="Getting Started", body="Tell us about you. Tap a section, then reply with your answer.")
    if up == "ONB_NAME":
        return _await(wa, "name", "Your Name", "Please reply with your full name.")
    if up == "ONB_MEDICAL":
        return _await(wa, "medical", "Medical / Injuries", "Any medical notes we should know?")
    if up == "ONB_TIMES":
        return _await(wa, "times", "Preferred Times", "Which days/times suit you? e.g., Mon & Wed 7–9am; Sat AM")
    if up == "ONB_TYPE":
        return _await(wa, "type", "Session Type", "Reply with: Single, Duo, or Group.")
    if up == "ONB_FREQ":
        return _await(wa, "freq", "Sessions / Week", "Reply with: 1x, 2x, or 3x.")
    if up == "ONB_SUBMIT":
        return _save_and_confirm(wa)

    # Fallback
    return _show_root_menu(wa)


def capture_onboarding_free_text(sender: str, raw_text: str):
    """Capture free-text input for whichever field is awaited."""
    wa = normalize_wa(sender)
    s = ONB_STATE.get(wa) or {}
    field = s.get("awaiting")
    if not field:
        return _show_root_menu(wa)

    value = (raw_text or "").strip()
    if field == "name":
        if len(value) < 2:
            return _ask_again(wa, "Name seems too short — please enter your full name.")
        value = value.title()[:120]
    elif field == "type":
        low = value.lower()
        if "group" in low:
            value = "group"
        elif "duo" in low:
            value = "duo"
        elif "single" in low or "private" in low:
            value = "single"
        else:
            return _ask_again(wa, "Please reply with: Single, Duo, or Group.")
    elif field == "freq":
        low = value.lower().replace("x", "")
        if "3" in low:
            value = "3x"
        elif "2" in low:
            value = "2x"
        elif "1" in low:
            value = "1x"
        else:
            return _ask_again(wa, "Please reply with 1x, 2x, or 3x per week.")
    # medical / times are free text; trim length
    if field in ("medical", "times"):
        value = value[:500]

    s[field] = value
    s["awaiting"] = None
    ONB_STATE[wa] = s

    return _stepper_menu(wa, header="Saved", body=f"✅ Saved your {field}. You can submit or fill the next item.")


# -------- internal helpers --------

def _show_root_menu(wa: str):
    body = (
        "✨ Welcome to PilatesHQ ✨\n"
        "Opening Special: Group @ R180 until January.\n"
        "🌐 pilateshq.co.za\n\n"
        "Choose an option:"
    )
    return send_whatsapp_list(
        wa, "PilatesHQ", body, "MAIN_MENU",
        [
            {"id": "ONB_START", "title": "📝 Get Started"},
            {"id": "UPDATE_DETAILS", "title": "✏️ Update My Details"},
        ]
    )


def _stepper_menu(wa: str, header: str, body: str):
    return send_whatsapp_list(
        wa, header, body, "ONB_MENU",
        [
            {"id": "ONB_NAME", "title": "👤 Name"},
            {"id": "ONB_MEDICAL", "title": "🩺 Medical"},
            {"id": "ONB_TIMES", "title": "⏰ Preferred Times"},
            {"id": "ONB_TYPE", "title": "🎯 Session Type"},
            {"id": "ONB_FREQ", "title": "📆 Sessions / Week"},
            {"id": "ONB_SUBMIT", "title": "✅ Submit"},
        ]
    )


def _await(wa: str, field: str, header: str, prompt: str):
    s = ONB_STATE.get(wa) or {"awaiting": None}
    s["awaiting"] = field
    ONB_STATE[wa] = s
    return send_whatsapp_list(
        wa, header, prompt, "ONB_BACK",
        [{"id": "ONB_START", "title": "⬅️ Onboarding"}]
    )


def _save_and_confirm(wa: str):
    s = ONB_STATE.get(wa, {})
    name    = (s.get("name") or "").strip()
    medical = (s.get("medical") or "").strip()
    times   = (s.get("times") or "").strip()
    sess_t  = (s.get("type") or "").strip().lower()
    freq    = (s.get("freq") or "").strip().lower()

    # plan mapping
    plan = "1x"
    if "3" in freq: plan = "3x"
    elif "2" in freq: plan = "2x"

    try:
        with get_session() as dbs:
            # Update name if provided
            if name:
                dbs.execute(text("UPDATE clients SET name = :nm WHERE wa_number = :wa"),
                            {"nm": name[:120], "wa": wa})
            dbs.execute(text("""
                UPDATE clients
                   SET medical_notes = :medical,
                       notes = :notes,
                       plan = :plan
                 WHERE wa_number = :wa
            """), {
                "medical": medical[:500],
                "notes": f"pref_times={times}; type={sess_t}"[:500],
                "plan": plan,
                "wa": wa
            })
        logging.info(f"[ONB] Saved profile wa={wa}")
    except Exception:
        logging.exception("[ONB] DB update failed")

    # Confirm to client
    body = (
        "✅ Thanks! Your details were sent to Nadine.\n"
        "She’ll confirm your plan/schedule and follow up."
    )
    send_whatsapp_list(
        wa, "Submitted", body, "AFTER_SUBMIT",
        [{"id": "ONB_START", "title": "📝 Edit Details"}, {"id": "MAIN_MENU", "title": "⬅️ Menu"}]
    )

    # Clear state
    ONB_STATE.pop(wa, None)
    return


def _ask_again(wa: str, prompt: str):
    return send_whatsapp_list(
        wa, "Try Again", prompt, "ONB_BACK",
        [{"id": "ONB_START", "title": "⬅️ Onboarding"}]
    )
