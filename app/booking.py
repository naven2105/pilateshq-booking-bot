# app/booking.py
from .utils import send_whatsapp_text

def show_bookings(wa_number: str):
    """
    Stub: Show upcoming bookings for a client.
    Replace with real DB queries later.
    """
    msg = (
        "📅 Your upcoming bookings:\n\n"
        "• Tue 24 Sep, 08:00 – Reformer Duo\n"
        "• Thu 26 Sep, 09:00 – Reformer Single\n\n"
        "If anything looks wrong, reply '0' and Nadine will assist."
    )
    send_whatsapp_text(wa_number, msg)
