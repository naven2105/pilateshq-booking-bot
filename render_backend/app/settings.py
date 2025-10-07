# app/settings.py

# ──────────────────────────────────────────────────────────────
# Central pricing & capacity settings
# Update these values when prices or class capacity change
# ──────────────────────────────────────────────────────────────

PRICING_RULES = {
    "single": 300,   # Single session (1 person)
    "duo": 250,      # Duo session (2 people)
    "group": 180,    # Group session (3 up to GROUP_MAX_CAPACITY)
}

# Max number of clients allowed in a group session
# (Change if new reformers are bought or sold)
GROUP_MAX_CAPACITY = 6

import os

# WhatsApp Cloud API
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "")

# Admin (Nadine) WhatsApp number
# Format: E.164 (no +, just digits, e.g., 27735534607)
ADMIN_NUMBER = os.getenv("ADMIN_NUMBER", "27735534607")

# App settings
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "your-verify-token")