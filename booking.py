# booking.py

def handle_booking_message(msg_text: str = "") -> str:
    """
    Handle PilatesHQ booking-related queries.
    Supports both free-text booking requests and button-triggered flow.
    """

    msg_text = (msg_text or "").lower()

    if "book" in msg_text:
        return "📅 To book a Pilates class, please tell me your preferred day and time."

    elif "schedule" in msg_text:
        return (
            "🗓️ This week's schedule:\n"
            "- Monday 6PM: Reformer Duo\n"
            "- Wednesday 7AM: Reformer Trio\n"
            "- Saturday 9AM: Reformer Single"
        )

    elif "class" in msg_text:
        return "Would you like to see the weekly schedule or directly book a class?"

    # Default when user clicks "📅 Book a Class" button
    return "📅 To book a Pilates class, please tell me your preferred day and time."
