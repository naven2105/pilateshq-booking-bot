# utils/error_handler.py
# User notification hook → sends a graceful fallback message to the client.
# Admin alert hook → sends detailed error logs to you/your team

# Retries transient failures (network/5xx).
# Notifies the user with a graceful fallback if retries fail.
# Alerts the admin with error details.

import logging
import requests
import time
from typing import Callable, Any, Dict

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class WhatsAppAPIError(Exception):
    """Custom exception for WhatsApp API errors."""


class ErrorHandler:
    def __init__(
        self,
        admin_alert_func: Callable[[str], None],
        user_notify_func: Callable[[str, str], None],
        max_retries: int = 3
    ):
        """
        :param admin_alert_func: function to send alerts to admin (WhatsApp/Email/Slack).
        :param user_notify_func: function to send graceful messages to users (to, msg).
        :param max_retries: max number of retries for transient errors.
        """
        self.admin_alert_func = admin_alert_func
        self.user_notify_func = user_notify_func
        self.max_retries = max_retries

    def request_with_retry(
        self,
        func: Callable,
        to_user: str,
        *args,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Wrap WhatsApp API requests with retry and error handling.
        :param func: function making the API call.
        :param to_user: WhatsApp number of the client (for graceful fallback).
        """
        retries = 0
        while retries <= self.max_retries:
            try:
                response = func(*args, **kwargs)
                status = response.get("status_code", 500)

                if 200 <= status < 300:
                    return response

                elif status == 401:
                    # Token invalid
                    self._alert_admin("❌ WhatsApp Token expired or invalid.")
                    self._notify_user(to_user, "⚠ Sorry, our service is temporarily unavailable. Please try again later.")
                    raise WhatsAppAPIError("Token invalid, manual intervention required.")

                elif 400 <= status < 500:
                    # Client error (payload/permissions)
                    msg = f"Client error {status}: {response}"
                    logger.error(msg)
                    self._alert_admin(f"⚠ Client error: {msg}")
                    self._notify_user(to_user, "⚠ We’re experiencing a problem. Please try again later.")
                    raise WhatsAppAPIError(msg)

                elif 500 <= status < 600:
                    # Retry for server errors
                    retries += 1
                    wait_time = 2 ** retries
                    logger.warning(f"Server error {status}, retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue

                else:
                    msg = f"Unexpected response: {response}"
                    self._alert_admin(msg)
                    self._notify_user(to_user, "⚠ Unexpected issue occurred. Please try again later.")
                    raise WhatsAppAPIError(msg)

            except requests.exceptions.RequestException as e:
                retries += 1
                wait_time = 2 ** retries
                logger.warning(f"Network error {e}, retrying in {wait_time}s...")
                time.sleep(wait_time)

        # All retries failed
        self._alert_admin("🚨 WhatsApp API unreachable after retries.")
        self._notify_user(to_user, "⚠ Our system is temporarily offline. Please try again later.")
        raise WhatsAppAPIError("Max retries exceeded.")

    def _alert_admin(self, message: str):
        """Send alert to admin via provided function."""
        logger.error(f"ALERT: {message}")
        self.admin_alert_func(message)

    def _notify_user(self, to_user: str, message: str):
        """Send fallback message to user via provided function."""
        logger.info(f"Notify user {to_user}: {message}")
        self.user_notify_func(to_user, message)

    def token_health_check(self, test_func: Callable) -> bool:
        """
        Periodic token validity test (e.g., call Graph API /me).
        """
        try:
            response = test_func()
            status = response.get("status_code", 500)
            if status == 200:
                return True
            elif status == 401:
                self._alert_admin("⚠ WhatsApp token invalid. Please refresh immediately.")
                return False
            else:
                logger.warning(f"Unexpected token check response: {response}")
                return False
        except Exception as e:
            self._alert_admin(f"Token health check failed: {e}")
            return False


# Example usage
if __name__ == "__main__":
    def dummy_admin_alert(msg: str):
        print(f"[ADMIN ALERT] {msg}")

    def dummy_user_notify(to: str, msg: str):
        print(f"[USER {to}] {msg}")

    def dummy_api_call():
        # Fake response simulating expired token
        return {"status_code": 401, "body": {"error": "Token expired"}}

    handler = ErrorHandler(
        admin_alert_func=dummy_admin_alert,
        user_notify_func=dummy_user_notify
    )

    try:
        handler.request_with_retry(dummy_api_call, to_user="+27735534607")
    except WhatsAppAPIError as e:
        print(f"Final Exception: {e}")
