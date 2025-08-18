# booking.py
from utils import send_whatsapp_buttons

def handle_booking_message(msg_text: str, sender: str) -> str:
    """
    Booking flow with buttons for PilatesHQ.
    Uses WhatsApp interactive replies for easier UX.
    Always includes a 'Return to Menu' option.
    """

    msg_text = msg_text.lower()

    # Entry point
    if msg_text == "book":
        send_whatsapp_buttons(
            sender,
            "📅 Please select the class type you'd like to book:",
            [
                {"id": "BOOK_SINGLE", "title": "💪 Single (R300)"},
                {"id": "BOOK_DUO", "title": "👯 Duo (R250 each)"},
                {"id": "BOOK_GROUP", "title": "👨‍👩‍👧‍👦 Group (3–6 @ R180 each)"},
                {"id": "MENU", "title": "🔙 Return to Menu"}
            ]
        )
        return None

    # Handle selections
    elif msg_text == "book_single":
        send_whatsapp_buttons(
            sender,
            "You selected **Single Session @ R300**.\n\n✅ Confirm booking?",
            [
                {"id": "CONFIRM_SINGLE", "title": "✅ Confirm"},
                {"id": "BOOK", "title": "🔄 Choose Again"},
                {"id": "MENU", "title": "🔙 Return to Menu"}
            ]
        )
        return None

    elif msg_text == "book_duo":
        send_whatsapp_buttons(
            sender,
            "You selected **Duo Session @ R250 each**.\n\n✅ Confirm booking?",
            [
                {"id": "CONFIRM_DUO", "title": "✅ Confirm"},
                {"id": "BOOK", "title": "🔄 Choose Again"},
                {"id": "MENU", "title": "🔙 Return to Menu"}
            ]
        )
        return None

    elif msg_text == "book_group":
        send_whatsapp_buttons(
            sender,
            "🎉 You selected **Group Session (3–6 clients @ R180 each)**.\n"
            "This is our opening special until January.\n\n✅ Confirm booking?",
            [
                {"id": "CONFIRM_GROUP", "title": "✅ Confirm"},
                {"id": "BOOK", "title": "🔄 Choose Again"},
                {"id": "MENU", "title": "🔙 Return to Menu"}
            ]
        )
        return None

    # Confirmation step
    elif msg_text.startswith("confirm_"):
        send_whatsapp_buttons(
            sender,
            "✅ Thank you! Your booking request has been received.\n"
            "Nadine will contact you to finalise your class time.\n\nWould you like to:",
            [
                {"id": "BOOK", "title": "📅 Book Another"},
                {"id": "MENU", "title": "🔙 Return to Menu"}
            ]
        )
        return None

    # Default fallback
    else:
        send_whatsapp_buttons(
            sender,
            "🤔 I didn’t understand. Please choose from the options below:",
            [
                {"id": "BOOK", "title": "📅 Book a Class"},
                {"id": "MENU", "title": "🔙 Return to Menu"}
            ]
        )
        return None
