from utils import send_whatsapp_buttons

# Store booking state in memory (later can move to DB)
BOOKING_STATE = {}

# Available class types
CLASS_TYPES = [
    {"id": "SINGLE", "title": "🧘 Single (R300)"},
    {"id": "DUO", "title": "👥 Duo (R250 each)"},
    {"id": "GROUP", "title": "👨‍👩‍👧 Group (3–6, R180 each)"},
]

# Available days
DAYS_OF_WEEK = [
    {"id": "MON", "title": "Monday"},
    {"id": "TUE", "title": "Tuesday"},
    {"id": "WED", "title": "Wednesday"},
    {"id": "THU", "title": "Thursday"},
    {"id": "FRI", "title": "Friday"},
    {"id": "SAT", "title": "Saturday"},
    {"id": "SUN", "title": "Sunday"},
]

# Time slots
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
    """
    Handles the step-by-step booking flow.
    """
    # Initialize booking state for user
    if sender not in BOOKING_STATE:
        BOOKING_STATE[sender] = {}

    # Step 1: Ask for class type
    if msg_text == "book":
        send_whatsapp_buttons(
            sender,
            "Which class type would you like to book?",
            buttons=CLASS_TYPES
        )
        return None

    # Step 2: Class type selected
    elif msg_text in [c["id"] for c in CLASS_TYPES]:
        BOOKING_STATE[sender]["class_type"] = next(c["title"] for c in CLASS_TYPES if c["id"] == msg_text)
        send_whatsapp_buttons(
            sender,
            "Great! Which day would you like to attend?",
            buttons=DAYS_OF_WEEK
        )
        return None

    # Step 3: Day selected
    elif msg_text in [d["id"] for d in DAYS_OF_WEEK]:
        BOOKING_STATE[sender]["day"] = next(d["title"] for d in DAYS_OF_WEEK if d["id"] == msg_text)
        send_whatsapp_buttons(
            sender,
            "Perfect! Please choose a time slot:",
            buttons=TIME_SLOTS
        )
        return None

    # Step 4: Time slot selected
    elif msg_text in [t["id"] for t in TIME_SLOTS]:
        BOOKING_STATE[sender]["time"] = next(t["title"] for t in TIME_SLOTS if t["id"] == msg_text)

        booking = BOOKING_STATE[sender]
        confirmation_text = (
            f"✅ Booking request received!\n\n"
            f"Class Type: {booking['class_type']}\n"
            f"Day: {booking['day']}\n"
            f"Time: {booking['time']}\n\n"
            f"Nadine will confirm your spot shortly."
        )

        # Send confirmation to user
        send_whatsapp_buttons(
            sender,
            confirmation_text,
            buttons=[{"id": "MENU", "title": "🔙 Return to Menu"}]
        )

        # 🔔 Notify Nadine
        nadine_number = "27843131635"  # WhatsApp format (replace 0 with 27)
        notify_text = (
            f"📢 New Booking Alert!\n\n"
            f"Client: {sender}\n"
            f"Class Type: {booking['class_type']}\n"
            f"Day: {booking['day']}\n"
            f"Time: {booking['time']}"
        )
        send_whatsapp_buttons(
            nadine_number,
            notify_text,
            buttons=[{"id": "MENU", "title": "🔙 Return to Menu"}]
        )
        return None

    else:
        send_whatsapp_buttons(
            sender,
            "Sorry, I didn’t understand that. Please choose an option:",
            buttons=[{"id": "MENU", "title": "🔙 Return to Menu"}]
        )
        return None
