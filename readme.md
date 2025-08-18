# PilatesHQ WhatsApp Bot

A modular WhatsApp chatbot built for **PilatesHQ** using **Flask, Meta WhatsApp Cloud API, and OpenAI GPT**.  
It supports **structured booking conversations** and **wellness Q&A powered by ChatGPT**.

---

## 🔑 Features

- Clean modular design:
  - **main.py** → Flask app + webhook routing
  - **booking.py** → Booking/business logic
  - **wellness.py** → ChatGPT-powered wellness assistant
  - **utils.py** → WhatsApp Cloud API helper
- Ready for **Render deployment** (Procfile + requirements.txt included)
- Flexible routing:
  - `1 ...` → Business/Bookings handled by `booking.py`
  - `2 ...` → Wellness Q&A handled by `wellness.py` (ChatGPT)
  - Other text → Echo response
- Securely uses **environment variables** for Meta + OpenAI tokens

---

## 🗂 Project Structure

├── main.py # Flask + routing
├── booking.py # Handles business/booking logic
├── wellness.py # ChatGPT wellness assistant
├── utils.py # WhatsApp API helper
├── requirements.txt
├── Procfile
└── README.md

## 📦 Dependencies

- **flask** → for the web server  
- **requests** → for sending messages to Meta Cloud API  
- **openai** → for wellness.py (ChatGPT calls)  
- **gunicorn** → production server that Render uses to run Flask apps 

