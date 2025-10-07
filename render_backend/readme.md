# PilatesHQ — Render Backend (Flask / Meta Webhook)

This folder contains the Flask backend that handles **real-time WhatsApp events** and integrates with the Google Apps Script automations.

## Overview
The Render server remains online to process incoming WhatsApp messages and trigger logic instantly — such as:
- Guest onboarding (prospect to client)
- Client registration
- Booking creation
- “RESCHEDULE” message detection
- Forwarding events to Google Apps Script (for logging and alerts)

Google Apps Script handles all scheduled automation (daily reminders, weekly messages, etc.) to reduce hosting costs.

## Folder Structure
| File | Purpose |
|------|----------|
| `app/router.py` | Main Flask webhook endpoint for WhatsApp Cloud API |
| `app/admin_nudge.py` | Sends admin notifications (new leads, updates, etc.) |
| `app/reschedule_forwarder.py` | Forwards “RESCHEDULE” messages to Google Apps Script |
| `app/utils.py` | Shared helper functions (e.g., WhatsApp message sending) |
| `app/db.py` | Handles PostgreSQL connections (client + booking data) |
| `requirements.txt` | Python dependencies |
| `render.yaml` | Render deployment configuration |

## Notes
- Meta webhook is configured to point to `/webhook` on this server.
- Outgoing scheduled messages (e.g., 06h00, 20h00) are now handled in Google Apps Script.
- Keep this backend running on the **free or lowest Render plan** — uptime only, no heavy cron jobs.
- Environment variables (`META_ACCESS_TOKEN`, `PHONE_NUMBER_ID`, `APPS_SCRIPT_URL`) are required for full integration.

## Future Simplification
Once all webhook logic (guest onboarding, booking, rescheduling) is migrated to Google Apps Script,
this Render backend can be decommissioned entirely.
