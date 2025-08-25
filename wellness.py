# app/wellness.py
from .utils import send_whatsapp_list

def handle_wellness_message(text: str, to: str):
    tips = (
        "Hydrate well, breathe deep, and focus on form.\n"
        "Want more? Ask me about posture, core, or recovery."
    )
    return send_whatsapp_list(
        to, "Wellness Tips", tips, "WELL_MENU",
        [{"id": "MAIN_MENU", "title": "⬅️ Menu"}]
    )
