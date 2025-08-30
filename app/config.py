# app/config.py
"""
Configuration & environment variables.
This module centralizes runtime settings pulled from the environment.
Nothing in here should perform network I/O or imports with side effects.
"""

import os

# --- Meta / WhatsApp Cloud API ---
# ACCESS_TOKEN: long-lived token for WhatsApp Cloud API (kept secret in Render env)
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN", "")
# PHONE_NUMBER_ID: numeric WA phone id from Meta (e.g., 802833389569115)
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "")
# VERIFY_TOKEN: shared secret for webhook verification (GET /webhook)
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "testtoken")

# Build WhatsApp messages endpoint url
# Docs: https://developers.facebook.com/docs/whatsapp/cloud-api/reference/messages
GRAPH_URL = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"

# --- Admin (single-admin mode) ---
# NADINE_WA can be 062..., +27..., or 27..., we normalize later.
NADINE_WA = os.environ.get("NADINE_WA", "")

# --- Database ---
DATABASE_URL = os.environ.get("DATABASE_URL", "")
