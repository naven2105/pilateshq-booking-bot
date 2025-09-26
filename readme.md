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

---

## 🗂 Project Structure

├── app/
│ ├── main.py # Flask + routing
│ ├── router.py # Webhook dispatcher
│ ├── booking.py # Booking logic
│ ├── admin_core.py # Admin (Nadine) commands
│ ├── admin_clients.py # Client management
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

## 🆕 WhatsApp Flows Support

This bot supports **Meta WhatsApp Flows** for structured forms.  
Nadine can trigger a published form (e.g. *Client Registration*) directly from WhatsApp.

### Setup

1. In **Meta Business Manager**, publish the Flow (e.g. `client_registration`).  
2. Copy the **Flow ID** (looks like `24571517685863108`).  
3. In Render → Environment → add:

   ```bash
   CLIENT_REGISTRATION_FLOW_ID=24571517685863108
