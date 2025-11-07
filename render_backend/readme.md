<!-- readme.md -->
# PilatesHQ — Render Backend (Flask / Meta Webhook)

This folder contains the Flask backend that powers the PilatesHQ Booking Bot — handling real-time WhatsApp automation and secure integrations with Google Apps Script.

---

## 🧭 Overview

The Render server remains online to process instant WhatsApp events and bridge them to Google Apps Script (GAS) for persistent automation and reporting.

### Real-time actions handled here
- Client onboarding & registration  
- Session bookings and reschedules  
- NLP message parsing (e.g. “Reschedule Mary Smith”)  
- Secure invoice generation & dual-channel delivery (WhatsApp + Email)  
- Payment logging & invoice matching  
- Admin notifications, summaries, and insights  
- Forwarding structured events to GAS for storage and dashboards  

⏰ All scheduled jobs (daily reminders, weekly summaries, auto-billing) run entirely inside Google Apps Script, keeping Render always-on but low-cost.

---

## 🗂️ Folder Structure (Phase 30)

| File | Purpose |
|------|----------|
| `app/__init__.py` | Registers all Flask blueprints — unified architecture (v1.10.0) |
| `app/router_webhook.py` | Core WhatsApp Cloud API event listener |
| `app/tasks_router.py` | **Phase 30** reminders (`/tasks/reminder/morning`, `/tasks/reminder/evening`) + client reminders |
| `app/tasks_sheets.py` | Shared Google Sheets read/write utilities |
| `app/client_reminders.py` | Sends Meta-approved templates to clients |
| `app/package_events.py` | Handles credit usage and low-balance alerts |
| `app/invoices_router.py` | ✅ Unified Invoices + Payments — PDF generation, delivery, logging, **/invoices/confirm** |
| `app/schedule_router.py` | ✅ Bookings + Reschedules + Admin Digests |
| `app/dashboard_router.py` | Weekly & monthly studio insight reports |
| `app/admin_actions_router.py` | NLP admin commands (discounts, session type changes) |
| `app/standing_router.py` | Recurring slot (“standing booking”) management |
| `app/admin_exports_router.py` | Phase 29: Client / Session Exports + UAT logging |
| `app/utils.py` | Shared helpers for WhatsApp messaging + GAS POST requests |
| `app/tokens.py` | Secure token encoding / decoding for invoice links |
| `app/static/pilateshq_logo.png` | Logo used in invoice PDF headers |

🗑️ **Removed / merged files**  
- `attendance_router.py` → merged into `schedule_router.py`  
- `payments_router.py` → merged into `invoices_router.py`  

---

## ⚙️ Environment Variables

| Variable | Description |
|-----------|-------------|
| META_ACCESS_TOKEN | WhatsApp Cloud API access token |
| PHONE_NUMBER_ID | PilatesHQ Business WhatsApp ID |
| GAS_WEBHOOK_URL | ✅ Unified GAS endpoint (v107) for exports/logging |
| GAS_INVOICE_URL | Google Apps Script endpoint for invoices & payments |
| CLIENT_SHEET_ID | Google Sheet ID for client / invoice data |
| NADINE_WA | Nadine’s WhatsApp number (for admin alerts) |
| BASE_URL | Public Render URL for secure invoice token links |
| TEMPLATE_LANG | Default Meta template locale (e.g. en_US) |
| SECRET_KEY | Token signing key for secure invoice links |
| REQUEST_TIMEOUT | Global request timeout (default 35s) |

*(Optional)* Gmail API credentials may still be used if direct email sending is re-enabled.

---

## 💼 Phase 30 — Automated Reminders & Invoice Flow UAT

**Objectives**
- GAS triggers 06h00 and 20h00 → call Flask:
  - `POST /tasks/reminder/morning`  
  - `POST /tasks/reminder/evening`
- GAS posts invoice confirmations to:
  - `POST /invoices/confirm` (records status and notifies Nadine)

**Behaviour**
- All reminder and invoice events send WhatsApp template alerts to Nadine.  
- Each event appends a compact line to the GAS `Logs` tab via `append_log_event`.  
- No CRON or APScheduler on Render — GAS orchestrates schedules.

---

## 🧩 System Integration Flow
Client Message → Meta Webhook → Flask (router_webhook)  
└→ NLP / schedule_router / invoices_router / tasks_router  
└→ Google Apps Script (write to Sheets, trigger logic)  
└→ Sends summaries & dashboards back via `/dashboard/*` and admin templates

All daily / weekly triggers (e.g. reminders, dashboards, auto-invoices) originate in Google Apps Script and POST to the corresponding Flask endpoint.

---

## 🧠 Operational Notes

- Meta Webhook URL → `/webhook`  
- GAS calls → authenticated HTTPS POST to Render endpoints  
- No CRON or APScheduler jobs run on Render  
- Backend may run on Render free tier since CPU use is minimal  
- Environment variables must be configured in Render Dashboard  

---

## 📘 Phase 25 — Reschedule Handling Policy

*(Unchanged — still active as baseline for session management)*

**Design Principle:**  
> All automation flows one-way — from *Active → Rescheduled*.  
> Only Nadine may reverse a reschedule manually.

---

✅ **Status:** Phase 30 Ready — Reminders & Invoice Confirmations integrated
