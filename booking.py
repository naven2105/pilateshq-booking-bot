import logging
from utils import send_whatsapp_list

def handle_booking_message(choice, sender):
    logging.info(f"[BOOKING FLOW] Choice: {choice}, Sender: {sender}")

    if choice == "BOOK":
        body = "Please select your class type 👇"
        options = [
            {"id": "BOOK_GROUP", "title": "👥 Group Class R180"},
            {"id": "BOOK_SINGLE", "title": "🙋 Single Class R300"},
            {"id": "BOOK_DUO", "title": "👫 Duo Class R250"}
        ]
        send_whatsapp_list(sender, "Class Types", body, "BOOK_CLASS_TYPE", options)

    elif choice == "BOOK_GROUP":
        body = "Choose your preferred time slot ⏰"
        options = [
            {"id": "SLOT_6AM", "title": "6am - 7am"},
            {"id": "SLOT_7AM", "title": "7am - 8am"},
            {"id": "SLOT_8AM", "title": "8am - 9am"},
            {"id": "SLOT_9AM", "title": "9am - 10am"},
            {"id": "SLOT_10AM", "title": "10am - 11am"},
            {"id": "SLOT_11AM", "title": "11am - 12pm"},
            {"id": "SLOT_12PM", "title": "12pm - 1pm"},
            {"id": "SLOT_1PM", "title": "1pm - 2pm"},
            {"id": "SLOT_2PM", "title": "2pm - 3pm"},
            {"id": "SLOT_3PM", "title": "3pm - 4pm"},
        ]
        send_whatsapp_list(sender, "Time Slots", body, "BOOK_GROUP_SLOT", options)

    elif choice.startswith("SLOT_"):
        send_whatsapp_list(sender, "Booking Confirmed ✅",
                           "Thank you! Your slot is reserved. You’ll receive reminders before class.",
                           "CONFIRM_MENU",
                           [{"id": "MAIN", "title": "⬅️ Back to Menu"}])

    else:
        logging.warning(f"[BOOKING FLOW] Unknown choice: {choice}")
