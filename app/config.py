import os

# --- Meta / WhatsApp Cloud API ---
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN", "")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "")  # e.g. 802833389569115
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "testtoken")

# Build the correct WA messages endpoint:
# https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages
GRAPH_URL = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"

# --- Admin (single-admin mode is fine) ---
NADINE_WA = os.environ.get("NADINE_WA", "")  # can be 062..., +27..., 27..., we'll normalize

# --- Database ---
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# --- Templates for outbound messages (outside 24h window) ---
# Create this template in WhatsApp Business Manager and APPROVE it first.
# Suggested template name/body:
#   Name: admin_update
#   Language: en
#   Body: "{{1}}"
# …so we can pass the entire text as a single variable.
ADMIN_TEMPLATE_NAME = os.environ.get("ADMIN_TEMPLATE_NAME", "admin_update")
ADMIN_TEMPLATE_LANG = os.environ.get("ADMIN_TEMPLATE_LANG", "en")
