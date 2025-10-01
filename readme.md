# PilatesHQ WhatsApp Bot

A modular WhatsApp chatbot built for **PilatesHQ** using **Flask, Meta WhatsApp Cloud API, and OpenAI GPT**.  
It supports **structured booking conversations**, **admin tools for Nadine**, and **wellness Q&A powered by ChatGPT**.

---

## 🔑 Features

- Clean modular design:
  - **main.py** → Flask app + webhook routing
  - **booking.py** → Booking/business logic
  - **wellness.py** → ChatGPT-powered wellness assistant
  - **utils.py** → WhatsApp Cloud API helper (templates, text, flows)
- Ready for **Render deployment** (Procfile + requirements.txt included)
- Flexible routing:
  - `ADMIN` (Nadine) → booking/attendance/client management
  - `CLIENT` → bookings, invoices, wellness Q&A
  - `PROSPECT` → lead capture + auto admin alerts
- Securely uses **environment variables** for Meta + OpenAI tokens
- Supports **WhatsApp Flows** for structured client registration
- **Admin alerts via Meta templates**: Nadine receives a template-approved notification + Add Client button when new leads arrive.

---

## 🗂 Project Structure

├── app/
│ ├── main.py # Flask + routing
│ ├── router.py # Webhook dispatcher
│ ├── booking.py # Booking logic
│ ├── admin_core.py # Admin (Nadine) commands
│ ├── admin_clients.py # Client management
│ ├── admin_bookings.py # Booking management
│ ├── admin_nlp.py # Lightweight NLP for admin
│ ├── client_nlp.py # Lightweight NLP for clients
│ ├── prospect.py # Prospect onboarding
│ ├── invoices.py # Invoice generation
│ ├── utils.py # WhatsApp API helpers (text, template, flow)
│ └── db.py # DB session helper
├── requirements.txt
├── Procfile
└── README.md


---

## 📦 Dependencies

- **flask** → for the web server  
- **requests** → for sending messages to Meta Cloud API  
- **openai** → for GPT-based assistant  
- **sqlalchemy** + **psycopg2** → database access  
- **gunicorn** → production server used by Render  

---

## 🆕 WhatsApp Flows & Admin Alerts

### Prospect → Admin Workflow
1. Guest sends first enquiry (e.g. “Hi” + name).  
2. Lead is stored in DB (`leads` table).  
3. Nadine receives a **Meta template notification**:

📢 Admin Alert
Hi: 📥 New Prospect: "John Doe (27735534607) at 2025-10-01 11:54", for your urgent attention 😉


- Uses template: `TPL_ADMIN_PROSPECT`  
- Variable `{{1}}` is populated with: `Name (WA Number) at Timestamp`

4. Notification also includes an **“Add Client”** button.  
- When clicked, opens the **Client Registration Flow**.  
- Prefills client name + mobile from the lead record.  

5. Nadine can confirm and register the client, then book them into sessions.

---

## 🔧 Environment Variables

Add the following in Render → **Environment**:

```bash
# Meta WhatsApp
WHATSAPP_TOKEN=...
PHONE_NUMBER_ID=...

# Verification
VERIFY_TOKEN=changeme

# OpenAI
OPENAI_API_KEY=...

# Admin setup
ADMIN_WA_LIST=2782...,2773...   # Nadine’s WA numbers (comma separated)

# Templates
TPL_ADMIN_PROSPECT=guest_query_alert

# WhatsApp Flows
CLIENT_REGISTRATION_FLOW_ID=24571517685863108

🚀 Deployment
# Local run
flask run --host=0.0.0.0 --port=5000

# Render deploy uses:
gunicorn app.main:app


✅ With this setup:

New guests → auto admin template alert + Add Client button.

Nadine → one-tap workflow: call guest → click Add Client → register → book session.