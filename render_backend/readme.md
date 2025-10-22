# PilatesHQ — Render Backend (Flask / Meta Webhook)

This folder contains the Flask backend that handles **real-time WhatsApp events** and integrates with the Google Apps Script automations.

---

## Overview
The Render server remains online to process incoming WhatsApp messages and trigger logic instantly — such as:
- Guest onboarding (prospect to client)
- Client registration
- Booking creation
- “RESCHEDULE” message detection
- Invoice generation and delivery (WhatsApp + Email)
- Forwarding events to Google Apps Script (for logging and alerts)

Google Apps Script handles all scheduled automation (daily reminders, weekly messages, etc.) to reduce hosting costs.

---

## Folder Structure
| File | Purpose |
|------|----------|
| `app/router.py` | Main Flask webhook endpoint for WhatsApp Cloud API |
| `app/admin_nudge.py` | Sends admin notifications (new leads, updates, etc.) |
| `app/invoices_router.py` | Handles invoice PDF generation and delivery (WhatsApp + Email) |
| `app/reschedule_forwarder.py` | Forwards “RESCHEDULE” messages to Google Apps Script |
| `app/utils.py` | Shared helper functions (e.g., WhatsApp message sending) |
| `app/db.py` | Handles PostgreSQL connections (client + booking data) |
| `requirements.txt` | Python dependencies |
| `render.yaml` | Render deployment configuration |

---

## Environment Variables
| Variable | Description |
|-----------|-------------|
| `META_ACCESS_TOKEN` | Access token for WhatsApp Cloud API |
| `PHONE_NUMBER_ID` | PilatesHQ business number for WhatsApp |
| `GAS_INVOICE_URL` | Google Apps Script endpoint for invoice actions |
| `CLIENT_SHEET_ID` | Google Sheet storing client and invoice data |
| `NADINE_WA` | Nadine’s WhatsApp number for admin alerts |
| `GMAIL_CLIENT_ID` / `GMAIL_CLIENT_SECRET` | (Optional) For Gmail API OAuth credentials if backend email used |

---

## Phase 9 — Dual-Channel Invoice Delivery (Email + WhatsApp)

**Objective:** Ensure each client receives invoices through both channels for reliability and compliance.

### Key Features
- Auto-generate PDF invoice with studio branding and secure tokenised link.  
- Deliver via **WhatsApp** (approved Meta template) and **Email** simultaneously.  
- Email sent using either:
  - **Option A:** Gmail API (OAuth credentials on Render), or  
  - **Option B:** Google Apps Script `MailApp.sendEmail()` when invoice is generated.  
- Maintain delivery logs with timestamp + status in Google Sheet or database.  
- Auto-alert Nadine on failed delivery.  
- Email template standardised:

  **Subject:** PilatesHQ Invoice – October 2025  
  **Body:**  
  > Dear Mary Smith,  
  > Please find attached your PilatesHQ invoice.  
  > For your security, this link will expire in 48 hours.  

---

## Notes
- Meta webhook is configured to point to `/webhook` on this server.  
- Outgoing scheduled messages (e.g., 06h00, 20h00) are handled in Google Apps Script.  
- Keep this backend running on the **free or lowest Render plan** — uptime only, no heavy cron jobs.  
- Environment variables (`META_ACCESS_TOKEN`, `PHONE_NUMBER_ID`, `APPS_SCRIPT_URL`) are required for full integration.  

---

## Future Simplification
Once all webhook and delivery logic (guest onboarding, booking, rescheduling, invoicing) are migrated fully to Google Apps Script,
this Render backend can eventually be decommissioned to minimise hosting costs.

---

✅ *Updated for Phase 9 – Dual-Channel Invoice Delivery (Pending Implementation)*
