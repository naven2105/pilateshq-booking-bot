import logging
from app.utils import send_whatsapp_list

# Per-user state
user_state = {}  # {sender: {"step","class_type","day_id","day_title","period","time_id","time_title"}}

# Class types (≤24 chars)
CLASS_ROWS = [
    {"id": "GROUP",  "title": "Group R180",  "description": "Open special, 3–6 ppl"},
    {"id": "DUO",    "title": "Duo R250",    "description": "Two clients"},
    {"id": "SINGLE", "title": "Single R300", "description": "One-on-one"},
]

# Days (≤10 rows)
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

# Periods as LIST (not buttons)
PERIOD_ROWS = [
    {"id": "PERIOD_MORN",  "title": "Morning 06–11"},
    {"id": "PERIOD_AFTER", "title": "Afternoon 12–15"},
    {"id": "PERIOD_EVE",   "title": "Evening 16–18"},
]

# Time rows by period (each ≤10)
TIME_ROWS_BY_PERIOD = {
    "PERIOD_MORN": [
        {"id": "TIME_06", "title": "06:00–07:00"},
        {"id": "TIME_07", "title": "07:00–08:00"},
        {"id": "TIME_08", "title": "08:00–09:00"},
        {"id": "TIME_09", "title": "09:00–10:00"},
        {"id": "TIME_10", "title": "10:00–11:00"},
        {"id": "TIME_11", "title": "11:00–12:00"},
    ],
    "PERIOD_AFTER": [
        {"id": "TIME_12", "title": "12:00–13:00"},
        {"id": "TIME_13", "title": "13:00–14:00"},
        {"id": "TIME_14", "title": "14:00–15:00"},
        {"id": "TIME_15", "title": "15:00–16:00"},
    ],
    "PERIOD_EVE": [
        {"id": "TIME_16", "title": "16:00–17:00"},
        {"id": "TIME_17", "title": "17:00–18:00"},
    ],
}

def handle_booking_message(msg_text: str, sender: str):
    """List → Class type, List → Day, List → Period, List → Time, confirm + notify Nadine."""
    code = (msg_text or "").strip().upper()
    state = user_state.get(sender, {"step": "start"})
    logging.info(f"[BOOK] {sender} step={state['step']} input={code}")

    # Start booking
    if code == "BOOK" or state["step"] == "start":
        user_state[sender] = {"step": "awaiting_class_type"}
        send_whatsapp_list(
            sender,
            header="Class Types",
            body="Please select your class type 👇",
            button_id="BOOK_CLASS",
            options=CLASS_ROWS
        )
        return

    # Class type chosen (GROUP/DUO/SINGLE)
    if state["step"] == "awaiting_class_type":
        if code not in {"GROUP", "DUO", "SINGLE"}:
            send_whatsapp_list(sender, "Class Types", "Please pick a class type:", "BOOK_CLASS", CLASS_ROWS); return
        state.update({"step": "awaiting_day", "class_type": code})
        user_state[sender] = state
        send_whatsapp_list(sender, "Pick a Day", "Choose your preferred day:", "BOOK_DAY", DAY_ROWS)
        logging.info(f"[BOOK] class_type -> {sender} | {code}")
        return

    # Day chosen (DAY_*)
    if state["step"] == "awaiting_day":
        if code not in DAY_MAP:
            send_whatsapp_list(sender, "Pick a Day", "Please choose a day:", "BOOK_DAY", DAY_ROWS); return
        state.update({"step": "awaiting_period", "day_id": code, "day_title": DAY_MAP[code]})
        user_state[sender] = state
        # PERIOD as LIST (was buttons)
        send_whatsapp_list(
            sender,
            header="Pick a Period",
            body=f"{state['day_title']} selected. Pick a time period:",
            button_id="BOOK_PERIOD",
            options=PERIOD_ROWS
        )
        logging.info(f"[BOOK] day -> {sender} | {state['day_title']}")
        return

    # Period chosen (PERIOD_*)
    if state["step"] == "awaiting_period":
        if code not in TIME_ROWS_BY_PERIOD:
            send_whatsapp_list(sender, "Pick a Period", "Please pick a time period:", "BOOK_PERIOD", PERIOD_ROWS); return
        state.update({"step": "awaiting_time", "period": code})
        user_state[sender] = state
        send_whatsapp_list(sender, "Time Slots", "Choose a time slot:", "BOOK_TIME", TIME_ROWS_BY_PERIOD[code])
        logging.info(f"[BOOK] period -> {sender} | {code}")
        return

    # Time chosen (TIME_*)
    if state["step"] == "awaiting_time":
        valid_map = {r["id"]: r["title"] for r in TIME_ROWS_BY_PERIOD[state["period"]]}
        if code not in valid_map:
            send_whatsapp_list(sender, "Time Slots", "Tap to pick a time:", "BOOK_TIME", TIME_ROWS_BY_PERIOD[state["period"]]); return
        state.update({"time_id": code, "time_title": valid_map[code]})
        user_state[sender] = state

        class_label = {"GROUP": "Group R180", "DUO": "Duo R250", "SINGLE": "Single R300"}[state["class_type"]]

        # Confirm to client
        confirm = (
            "✅ Booking request received!\n\n"
            f"Class: {class_label}\nDay: {state['day_title']}\nTime: {state['time_title']}\n\n"
            "Nadine will confirm your spot shortly."
        )
        send_whatsapp_list(
            sender, "Booking Confirmed", confirm, "CONFIRM_MENU",
            [{"id": "MAIN_MENU", "title": "⬅️ Back to Menu"}]
        )

        # Notify Nadine
        nadine = "27843131635"
        admin = (
            "📢 New Booking\n\n"
            f"Client: {sender}\nClass: {class_label}\nDay: {state['day_title']}\nTime: {state['time_title']}"
        )
        send_whatsapp_list(nadine, "New Booking", admin, "ADMIN_MENU", [{"id": "MAIN_MENU", "title": "Back to Menu"}])
        logging.info(f"[BOOK] confirm -> {sender} | {state}")

        # Clear state
        user_state.pop(sender, None)
        return

    # Fallback
    send_whatsapp_list(
        sender, "Bookings", "Let's start a booking:", "BOOK_START",
        [{"id": "BOOK", "title": "📅 Book a Class"}]
    )
