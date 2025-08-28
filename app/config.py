# app/config.py
import os

# Meta / WhatsApp API
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN", "")
GRAPH_URL = os.environ.get("GRAPH_URL", "https://graph.facebook.com/v20.0/me/messages")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "testtoken")

# Admin numbers
NADINE_WA = os.environ.get("NADINE_WA", "")  # single primary admin
ADMIN_WA_LIST = os.environ.get("ADMIN_WA_LIST", "")  # optional comma-separated list
# Example ENV value: "0627597357,0841234567"

# Database
DATABASE_URL = os.environ.get("DATABASE_URL", "")
