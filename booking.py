# booking.py

from datetime import datetime
from utils import send_whatsapp_message

# In-memory store (later we’ll replace with DB or Google Calendar)
bookings = {
    # Example structure:
    # "2025-08-18 18:00": {"type": "Group", "capacity": 6, "clients": ["+2782xxxxxx"]}
}


def handle_booking_message(msg_text: str, sender: str) -> str:
    """
    Handle PilatesHQ booking-related queries.
    - Promotes Group sessions first
    - Tracks bookings per slot (in memory)
    - Notifies Nadine
    """
    msg_text = msg_text.lower()

    # 1️⃣ Promote Group option if user just types "book"
    if msg_text in ["book", "booking", "class", "classes"]:
        return (
            "📅 Which class would you like to book?\n"
            "1. Group (R180, 3–6 clients, 🎉 opening special)\n"
            "2. Duo (R250)\n"
            "3. Single (R300)\n\n"
            "👉 Please reply with 'Group', 'Duo', or 'Single'."
        )

    # 2️⃣ Class type selection
    if "group" in msg_text:
        return "Great choice 🎉 Group Reformer at R180!\nPlease tell me your preferred day and time (e.g., 'Wednesday 6PM')."

    if "duo" in msg_text:
        return "You selected Duo @ R250.\nPlease tell me your preferred day and time (e.g., 'Wednesday 6PM')."

    if "single" in msg_text:
        return "You selected Single @ R300.\nPlease tell me your preferred day and time (e.g., 'Wednesday 6PM')."

    # 3️⃣ Handle date/time input (very basic parse for now)
    if any(word in msg_text for word in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]):
        # Default: assume last chosen type was Group (simplification for MVP)
        chosen_type = "Group" if "group" in msg_text else "Group"

        # Key = date/time string (for now just use raw input)
        slot_key = msg_text

        if slot_key not in bookings:
            bookings[slot_key] = {"type": chosen_type, "capacity": 6 if chosen_type == "Group" else 1, "clients": []}

        if len(bookings[slot_key]["clients"]) < bookings[slot_key]["capacity"]:
            bookings[slot_key]["clients"].append(sender)

            # ✅ Confirmation to client
            confirmation = f"✅ Booking confirmed!\nClass: {bookings[slot_key]['type']}\nTime: {slot_key}\nWe’ll send you reminders before your session."

            # 📩 Notify Nadine
            nadine_number = "27843131635"  # Nadine’s WhatsApp in international format
            notify_msg = f"📢 New Booking!\nClient: {sender}\nClass: {bookings[slot_key]['type']}\nTime: {slot_key}"
            send_whatsapp_message(nadine_number, notify_msg)

            return confirmation
        else:
            return f"❌ Sorry, the {slot_key} session is fully booked. Please choose another time."

    # 4️⃣ Default help response
    return "For bookings, please type 'book' to get started."
