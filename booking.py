# booking.py

def handle_booking_message(msg_text: str) -> str:
    """
    Handle PilatesHQ booking-related queries.
    For now, replies are static — later we’ll connect to a booking DB/system.
    """
    if "book" in msg_text:
        return "To book a Pilates class, please tell me your preferred day and time."
    elif "schedule" in msg_text:
        return "This week's schedule:\n- Monday 6PM: Reformer Duo\n- Wednesday 7AM: Reformer Trio\n- Saturday 9AM: Reformer Single"
    else:
        return "For bookings, please type 'book' or 'schedule'."
