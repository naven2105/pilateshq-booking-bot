import logging
from utils import send_whatsapp_buttons, send_whatsapp_list

# Per-user state
user_state = {}  # {sender: {"step": "...", "class_type": "...", "day_id": "...", "day_title": "...", "time_id": "...", "time_title": "..."}}

CLASS_BUTTONS = [
    {"id": "GROUP", "title": "👥 Group (R180)"},
    {"id": "DUO", "title": "👫 Duo (R250)"},
    {"id": "SINGLE", "title": "🧍 Single (R300)"},
]

DAY_ROWS = [
    {"id": "DAY_MON", "title": "Monday"},
    {"id": "DAY_TUE", "title": "Tuesday"},
    {"id": "DAY_WED", "title": "Wednesday"},
    {"id": "DAY_THU", "title": "Thursday"},
    {"id": "DAY_FRI", "title": "Friday"},
    {"id": "DAY_SAT", "title": "Saturday"},
    {"id": "DAY_SUN", "title": "Sunday"},
]
DAY_MAP = {r["id"]: r["title"] for r in DAY_ROWS}

TIME_ROWS = [
    {"id": "TIME_06", "title": "06:00 – 07:00"},
    {"id": "TIME_07", "title": "07:00 – 08:00"},
    {"id": "TIME_08", "title": "08:00 – 09:00"},
    {"id": "TIME_09", "title": "09:00 – 10:00"},
    {"id": "TIME_10", "title": "10:00 – 11:00"},
    {"id": "TIME_11", "title": "11:00 – 12:00"},
    {"id": "TIME_12", "title": "12:00 – 13:00"},
    {"id": "TIME_13", "title": "13:00 – 14:00"},
    {"id": "TIME_14", "title": "14:00 – 15:00"},
    {"id": "TIME_15", "title": "15:00 – 16:00"},
    {"id": "TIME_16", "title": "16:00 – 17:00"},
    {"id": "TIME_17", "title": "17:00 – 18:00"},
]
TIME_MAP = {r["id"]: r["title"] for r in TIME_ROWS}

def handle_booking_message(msg_text: str, sender: str):
    """Buttons → Class type, List → Day, List → Time, then confirm + notify Nadine."""
    msg_text = (msg_text or "").strip().upper()
    state = user_state.get(sender, {"step": "start"})
    logging.info(f"[BOOK] {sender} step={state['step']} input={msg_text}")

    # Start booking
    if msg_text == "BOOK" or state["step"] == "start":
        user_state[sender] = {"step": "awaiting_class_type"}
        send_whatsapp_buttons(sender, "Please select your class type:", CLASS_BUTTONS)
        return

    # Class type chosen (button ids)
    if state["step"] == "awaiting_class_type":
        if msg_text not in {"GROUP", "DUO", "SINGLE"}:
            send_whatsapp_buttons(sender, "Please choose a class type:", CLASS_BUTTONS)
            return
        state.update({"step": "awaiting_day", "class_type": msg_text})
        user_state[sender] = state
        logging.info(f"[BOOK] class_type -> {sender} | {msg_text}")
        send_whatsapp_list(sender, "Great! Choose your preferred day:", "Select day", DAY_ROWS, "Days")
        return

    # Day chosen (list reply id = DAY_*)
    if state["step"] == "awaiting_day":
        if msg_text not in DAY_MAP:
            send_whatsapp_list(sender, "Tap to pick a day:", "Select day", DAY_ROWS, "Days")
            return
        state.update({"step": "awaiting_time", "day_id": msg_text, "day_title": DAY_MAP[msg_text]})
        user_state[sender] = state
        logging.info(f"[BOOK] day -> {sender} | {state['day_title']}")
        send_whatsapp_list(sender, "Awesome! Now choose a time slot:", "Select time", TIME_ROWS, "Time Slots")
        return

    # Time chosen (list reply id = TIME_*)
    if state["step"] == "awaiting_time":
        if msg_text not in TIME_MAP:
            send_whatsapp_list(sender, "Tap to pick a time:", "Select time", TIME_ROWS, "Time Slots")
            return
        state.update({"time_id": msg_text, "time_title": TIME_MAP[msg_text]})
        user_state[sender] = state

        class_label = {"GROUP": "Group (R180)", "DUO": "Duo (R250)", "SINGLE": "Single (R300)"}[state["class_type"]]
        confirm_text = (
            "✅ Booking request received!\n\n"
            f"Class Type: {class_label}\n"
            f"Day: {state['day_title']}\n"
            f"Time: {state['time_title']}\n\n"
            "Nadine will confirm your spot shortly."
        )
        # Confirm to client
        send_whatsapp_buttons(sender, confirm_text, [{"id": "MENU", "title": "🏠 Return to Menu"}])

        # Notify Nadine
        nadine = "27843131635"
        admin_text = (
            "📢 New Booking\n\n"
            f"Client: {sender}\n"
            f"Class: {class_label}\n"
            f"Day: {state['day_title']}\n"
            f"Time: {state['time_title']}"
        )
        send_whatsapp_buttons(nadine, admin_text, [{"id": "MENU", "title": "Back to Menu"}])
        logging.info(f"[BOOK] confirm -> {sender} | {state}")

        # Clear state
        user_state.pop(sender, None)
        return

    # Fallback
    send_whatsapp_buttons(sender, "Let’s start a booking:", [{"id": "BOOK", "title": "📅 Book a Class"}])
