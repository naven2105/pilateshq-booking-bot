# router.py – replace your public handler logic with this

from .crud import upsert_public_client, client_exists_by_wa  # ensure these exist
from .utils import normalize_wa, reply_to_whatsapp

FAQS = {
    "address": "We’re at 71 Grant Ave, Norwood, Johannesburg. Safe off-street parking is available.",
    "group sizes": "Groups are capped at 6 to keep coaching personal.",
    "equipment": "We use Reformers, Wall Units, Wunda chairs, Wunda chairs, small props, and mats.",
    "pricing": "Groups from R180. Singles/Duos on request.",
    "schedule": "Weekdays 06:00–18:00; Sat 08:00–10:00.",
    "how to start": "Most start with a 1:1 assessment, then a first class in a small group.",
}

MAIN_MENU = (
    "\n\n*Menu*"
    "\n• address"
    "\n• group sizes"
    "\n• equipment"
    "\n• pricing"
    "\n• schedule"
    "\n• how to start"
    "\n• book"
)

def _looks_like_name(msg: str) -> str | None:
    m = msg.strip()
    if m.lower().startswith("name:"):
        n = m.split(":", 1)[1].strip()
        return n if len(n) >= 2 else None
    # simple heuristic: 2–5 words, letters/space/’- only
    if 2 <= len(m.split()) <= 5 and all(part.replace("-", "").isalpha() for part in m.split()):
        return m
    return None

def handle_public_message(sender_wa: str, text_lower: str, body_raw: str) -> None:
    to = sender_wa

    # 1) BOOKING INTENT (takes priority over FAQ)
    if text_lower in {"book", "booking", "join", "start"}:
        # Ask for name if we don't have this contact; or allow "name: ..." inline
        n = _looks_like_name(body_raw)
        if n:
            upsert_public_client(wa=to, name=n)  # creates if missing, updates name if exists
            reply_to_whatsapp(
                to,
                f"Great to meet you, *{n}*! 🎉\n"
                "We’ll message you with available slots to get started.\n"
                "If you already know your preferred days/times, reply here.\n"
                + MAIN_MENU
            )
            return

        # If client already exists we still allow updating name via “name: …”
        if client_exists_by_wa(to):
            reply_to_whatsapp(
                to,
                "Awesome — you’re on our list already. If your name is different on WhatsApp,"
                " reply with *Name: Your Full Name*.\n"
                "Or tell us your preferred days/times and we’ll confirm a spot.\n"
                + MAIN_MENU
            )
            return

        reply_to_whatsapp(
            to,
            "Let’s get you set up! Please reply with *Name: Your Full Name* (e.g., *Name: Alex Jacobs*)."
            + MAIN_MENU
        )
        return

    # 2) QUICK NAME CAPTURE (user may paste name without first typing 'book')
    name_guess = _looks_like_name(body_raw)
    if name_guess:
        upsert_public_client(wa=to, name=name_guess)
        reply_to_whatsapp(
            to,
            f"Thanks, *{name_guess}*! You’re on our list — we’ll reach out shortly with times.\n"
            "If you have preferred days/times, reply here.\n"
            + MAIN_MENU
        )
        return

    # 3) FAQ: exact keyword match first
    if text_lower in FAQS:
        reply_to_whatsapp(to, f"{FAQS[text_lower]}{MAIN_MENU}")
        return

    # 4) Fuzzy intent → map common phrases to the nearest FAQ
    if any(k in text_lower for k in ["where", "address", "location", "parking"]):
        reply_to_whatsapp(to, f"{FAQS['address']}{MAIN_MENU}")
        return
    if any(k in text_lower for k in ["price", "cost", "how much"]):
        reply_to_whatsapp(to, f"{FAQS['pricing']}{MAIN_MENU}")
        return
    if any(k in text_lower for k in ["hour", "open", "when", "time", "schedule"]):
        reply_to_whatsapp(to, f"{FAQS['schedule']}{MAIN_MENU}")
        return
    if "equipment" in text_lower or "reformer" in text_lower:
        reply_to_whatsapp(to, f"{FAQS['equipment']}{MAIN_MENU}")
        return
    if "start" in text_lower or "first class" in text_lower:
        reply_to_whatsapp(to, f"{FAQS['how to start']}{MAIN_MENU}")
        return

    # 5) Default welcome + menu
    reply_to_whatsapp(
        to,
        "Hi! I can help with studio info and getting you booked in. "
        "Try *address*, *pricing*, *schedule*, or *book* to begin."
        + MAIN_MENU
    )
