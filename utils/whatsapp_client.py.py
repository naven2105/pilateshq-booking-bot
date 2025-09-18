# utils/whatsapp_client.py
# Industry-standard, Is your official WhatsApp API client wrapper with error handling built in.

import os
import requests
from typing import List, Dict, Any
from utils.error_handler import ErrorHandler, WhatsAppAPIError


# === CONFIG from environment ===
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
ADMIN_NUMBER = os.getenv("ADMIN_WHATSAPP_NUMBER")

if not (PHONE_NUMBER_ID and ACCESS_TOKEN and ADMIN_NUMBER):
    raise RuntimeError("Missing required environment variables for WhatsApp client")

WHATSAPP_API_URL = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"

# --- Dummy implementations for demo ---
def send_admin_alert(msg: str):
    """Send alert to admin (WhatsApp, email, Slack, etc.)."""
    print(f"[ADMIN ALERT] {msg}")
    # TODO: Replace with actual send_whatsapp_text() to admin


def send_user_notify(to: str, msg: str):
    """Send fallback message to user via WhatsApp."""
    print(f"[USER {to}] {msg}")
    # TODO: Replace with actual send_whatsapp_text() to user


class WhatsAppClient:
    def __init__(self, api_url: str, access_token: str):
        self.api_url = api_url
        self.access_token = access_token
        self.handler = ErrorHandler(
            admin_alert_func=send_admin_alert,
            user_notify_func=send_user_notify
        )

    def _call_api(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Low-level WhatsApp API call."""
        try:
            resp = requests.post(
                self.api_url,
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=10
            )
            return {"status_code": resp.status_code, "body": resp.json()}
        except Exception as e:
            return {"status_code": 500, "body": {"error": str(e)}}

    def send_template(
        self,
        to: str,
        name: str,
        lang: str,
        variables: List[str]
    ) -> Dict[str, Any]:
        """Send a WhatsApp template with error handling."""
        components = [{
            "type": "body",
            "parameters": [{"type": "text", "text": str(v)} for v in variables],
        }]

        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": name,
                "language": {"code": lang},
                "components": components,
            },
        }

        try:
            return self.handler.request_with_retry(
                self._call_api,
                to,  # user number for fallback
                payload
            )
        except WhatsAppAPIError as e:
            return {"ok": False, "error": str(e)}

    def send_text(self, to: str, message: str) -> Dict[str, Any]:
        """Send a plain WhatsApp text message with error handling."""
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": message},
        }
        try:
            return self.handler.request_with_retry(
                self._call_api,
                to,
                payload
            )
        except WhatsAppAPIError as e:
            return {"ok": False, "error": str(e)}


# === Example usage ===
if __name__ == "__main__":
    client = WhatsAppClient(api_url=WHATSAPP_API_URL, access_token=ACCESS_TOKEN)

    resp = client.send_template(
        to="+27735534607",
        name="booking_confirm",
        lang="en",
        variables=["Naven", "Tomorrow 10AM"]
    )
    print("Template Response:", resp)

    resp2 = client.send_text(
        to="+27735534607",
        message="This is a test message with error handling."
    )
    print("Text Response:", resp2)
