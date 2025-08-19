import logging
from utils import send_whatsapp_buttons

# Per-user booking state
user_state = {}  # {sender: {"step": "...", "class_type": "...", "day": "...", "time": "..."}}

DAYS = [
    {"id": "MONDAY", "title": "Monday"},
    {"id": "TUESDAY", "title": "Tuesday"},
    {"id": "WEDNESDAY", "title": "Wednesday"},
    {"id": "THURSDAY", "title": "Thursday"},
    {"id": "FRIDAY", "title": "Friday"},
    {"id": "SATURDAY", "title": "Saturday"},
    {"id": "SUNDAY", "title": "Sunday"},
]

TIME_SLOTS = [
    {"id": "6AM", "title": "06:00 – 07:00"},
    {"id": "7AM", "title": "07:00 – 08:00"},
    {"id": "8AM", "title": "08:00 – 09:00"},
    {"id": "9AM", "title": "09:00 – 10:00"},
    {"id": "10AM", "title": "10:00 – 11:00"},
    {"id": "11AM", "title": "11:00 – 12:00"},
    {"id": "12PM", "title": "12:00 – 13:00"},
    {"id": "1PM", "title": "13:00 – 14:00"},
    {"id": "2PM", "title": "14:00 – 15:00"},
    {"id": "3PM", "title": "15:00 – 16:00"},
    {"id": "4PM", "title": "16:00 – 17:00"},
    {"id": "5PM", "title": "17:00 – 18:00"},
]

def handle_booking_message(msg_text: str, sender: str):
    """Stateful booking: Class → Day → Time → Confirm + notify Nadine."""
    msg_text = (msg_text or "").strip().upper()
    state = user_state.get(sender, {"step": "start"})
    logging.info(f"[BOOK] {sender} step={state['step']} input={msg_text}")

    # Start flow
    if msg_text == "BOOK" or state["step"] == "start":
        user_state[sender] = {"step": "awaiting_class_type"}
        logging.info(f"[BOOK] start -> {sender}")
        send_whatsapp_buttons(
            sender,
            "Please select your class type:",
            [{"id": "GROUP", "title": "👥 Group (R180 opening special)"},
             {"id": "DUO", "title": "👫 Duo (R250 each)"},
             {"id": "SINGLE", "title": "🧍 Single (R300)"}]
        )
        return

    # Class type chosen → Day
    if state["step"] == "awaiting_class_type":
        if msg_text not in ("GROUP", "DUO", "SINGLE"):
            send_whatsapp_buttons(sender, "Please choose a class type from the buttons above.")
            return
        user_state[sender] = {"step": "awaiting_day", "class_type": msg_text}
        logging.info(f"[BOOK] class_type -> {sender} | {msg_text}")
        send_whatsapp_buttons(sender, "Great! Which day works?", DAYS)
        return

    # Day chosen → Time
    if state["step"] == "awaiting_day":
        valid_days = {d["id"] for d in DAYS}
        if msg_text not in valid_days:
            send_whatsapp_buttons(sender, "Please pick a day from the buttons.")
            return
        state["day"] = msg_text.title()
        state["step"] = "awaiting_time"
        user_state[sender] = state
        logging.info(f"[BOOK] day -> {sender} | {state['day']}")
        send_whatsapp_buttons(sender, f"{state['day']} selected. Choose a time slot:", TIME_SLOTS)
        return

    # Time chosen → Confirm + notify
    if state["step"] == "awaiting_time":
        valid_times = {t["id"] for t in TIME_SLOTS}
        if msg_text not in valid_times:
            send_whatsapp_buttons(sender, "Please choose a time from the buttons.")
            return
        state["time"] = next(t["title"] for t in TIME_SLOTS if t["id"] == msg_text)
        user_state[sender] = state
        logging.info(f"[BOOK] time -> {sender} | {state['time']}")

        class_label = {
            "GROUP": "Group (R180)",
            "DUO": "Duo (R250 each)",
            "SINGLE": "Single (R300)",
        }[state["class_type"]]

        confirm_text = (
            "✅ Booking request received!\n\n"
            f"Class Type: {class_label}\n"
            f"Day: {state['day']}\n"
            f"Time: {state['time']}\n\n"
            "Nadine will confirm your spot shortly."
        )
        # Send confirmation to client
        send_whatsapp_buttons(sender, confirm_text, [{"id": "MENU", "title": "🏠 Return to Menu"}])

        # Notify Nadine
        nadine_number = "27843131635"
        admin_text = (
            "📢 New Booking\n\n"
            f"Client: {sender}\n"
            f"Class: {class_label}\n"
            f"Day: {state['day']}\n"
            f"Time: {state['time']}"
        )
        send_whatsapp_buttons(nadine_number, admin_text, [{"id": "MENU", "title": "Back to Menu"}])
        logging.info(f"[BOOK] confirm -> {sender} | {state}")

        # Clear state after completion
        user_state.pop(sender, None)
        return

    # Fallback inside booking
    send_whatsapp_buttons(sender, "Let's continue your booking:", [{"id": "BOOK", "title": "📅 Book a Class"}])
