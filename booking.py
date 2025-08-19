import logging
from utils import send_whatsapp_buttons

# Track user booking states
user_booking_state = {}

def handle_booking_message(msg_text: str, sender: str):
    """
    Booking flow with logging for debugging.
    """
    logging.info(f"Booking flow started for {sender}, input: {msg_text}")

    # Initialise state if new user
    if sender not in user_booking_state:
        user_booking_state[sender] = {"step": "class_type"}
        logging.info(f"New booking started for {sender}. Asking class type.")
        send_whatsapp_buttons(sender, "Which class type?", [
            {"id": "GROUP", "title": "👥 Group Class (R180)"},
            {"id": "SINGLE", "title": "🧍 Single Session (R300)"},
            {"id": "DUO", "title": "👫 Duo Session (R250)"}
        ])
        return "Please select your class type."

    # Continue booking flow
    step = user_booking_state[sender]["step"]
    logging.info(f"User {sender} is at step: {step}")

    if step == "class_type":
        user_booking_state[sender]["class_type"] = msg_text
        user_booking_state[sender]["step"] = "day"
        logging.info(f"Class type chosen: {msg_text}. Asking day next.")
        send_whatsapp_buttons(sender, "Select a day:", [
            {"id": "MONDAY", "title": "Monday"},
            {"id": "TUESDAY", "title": "Tuesday"},
            {"id": "WEDNESDAY", "title": "Wednesday"},
            {"id": "THURSDAY", "title": "Thursday"},
            {"id": "FRIDAY", "title": "Friday"},
            {"id": "SATURDAY", "title": "Saturday"},
            {"id": "SUNDAY", "title": "Sunday"},
        ])
        return "Pick your preferred day."

    elif step == "day":
        user_booking_state[sender]["day"] = msg_text
        user_booking_state[sender]["step"] = "time"
        logging.info(f"Day chosen: {msg_text}. Asking time next.")
        send_whatsapp_buttons(sender, "Select a time slot:", [
            {"id": "6AM", "title": "6am - 7am"},
            {"id": "7AM", "title": "7am - 8am"},
            {"id": "8AM", "title": "8am - 9am"},
            {"id": "9AM", "title": "9am - 10am"},
            {"id": "10AM", "title": "10am - 11am"},
            {"id": "11AM", "title": "11am - 12pm"},
            {"id": "12PM", "title": "12pm - 1pm"},
            {"id": "1PM", "title": "1pm - 2pm"},
            {"id": "2PM", "title": "2pm - 3pm"},
            {"id": "3PM", "title": "3pm - 4pm"},
            {"id": "4PM", "title": "4pm - 5pm"},
            {"id": "5PM", "title": "5pm - 6pm"},
        ])
        return "Pick your preferred time slot."

    elif step == "time":
        user_booking_state[sender]["time"] = msg_text
        class_type = user_booking_state[sender]["class_type"]
        day = user_booking_state[sender]["day"]
        time = user_booking_state[sender]["time"]

        logging.info(f"Booking confirmed for {sender}: {class_type}, {day}, {time}")
        confirmation = f"✅ Booking confirmed!\n\nClass: {class_type}\nDay: {day}\nTime: {time}\n\nWe’ll send reminders before your session."
        user_booking_state.pop(sender, None)  # reset
        return confirmation

    else:
        logging.warning(f"Unexpected booking step for {sender}: {step}")
        return "Something went wrong in the booking flow. Please start again."
