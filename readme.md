# PilatesHQ Studio WhatsApp Chatbot

A WhatsApp chatbot for **PilatesHQ Studio** with dual functionality:

1. **Booking Management** – Automates Pilates class bookings, manages schedule details, and confirms appointments.
2. **Customer Support** – Answers general queries in a friendly, conversational tone using ChatGPT. Escalates complex or personal requests directly to Nadine’s WhatsApp for personalised assistance.

Built with **Flask**, **Twilio WhatsApp API**, and **OpenAI GPT** to streamline studio operations and provide an engaging client experience.

---

## Features

* 📅 **Class Bookings** – Supports Reformer Single, Duo, and Trio bookings.
* 🤖 **AI-Powered Queries** – Uses ChatGPT to answer common studio-related questions.
* 📲 **Escalation to Human** – Routes special requests to Nadine’s personal WhatsApp.
* ☁️ **Cloud Deployment** – Ready for Render, Railway, or Heroku.
* 📝 **Booking Storage** – Currently in-memory (can be upgraded to Google Sheets or database).

---

## Prerequisites

Before running this bot, you’ll need:

* A **Twilio** account with **WhatsApp Sandbox** or a registered WhatsApp Business number.
* **Python 3.9+** installed.
* **OpenAI API key** (if AI responses are enabled).
* GitHub account for code hosting.
* A **Render** (or other cloud hosting) account for deployment.

---

## Local Setup

1. **Clone the repository**

   ```bash
   git clone https://github.com/naven2105/pilateshq-whatsapp-bot.git
   cd pilateshq-whatsapp-bot
   ```

2. **Create a virtual environment**

   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

4. **Create a `.env` file**
   Add your environment variables:

   ```env
   TWILIO_ACCOUNT_SID=your_twilio_sid
   TWILIO_AUTH_TOKEN=your_twilio_auth
   OPENAI_API_KEY=your_openai_key
   ```

5. **Run locally**

   ```bash
   python app.py
   ```

---

## Twilio Setup

1. Go to [Twilio Console](https://console.twilio.com/).
2. Enable **WhatsApp Sandbox** (or connect your business number).
3. Set the webhook URL to:

   ```
   https://<your-domain>/whatsapp
   ```
4. Add your approved message templates in **Meta Business Manager**.

---

## Deployment (Render Example)

1. Push your code to GitHub:

   ```bash
   git init
   git add .
   git commit -m "Initial commit - PilatesHQ Bot"
   git branch -M main
   git remote add origin https://github.com/naven2105/pilateshq-whatsapp-bot.git
   git push -u origin main
   ```

2. On [Render](https://render.com/):

   * Create a **New Web Service**.
   * Connect your GitHub repo.
   * Add environment variables from your `.env` file.
   * Set `Start Command` to:

     ```
     gunicorn app:app
     ```

3. Deploy and copy your live URL into Twilio’s webhook settings.

---

## Future Enhancements

* Save bookings to Google Sheets or database.
* Allow rescheduling/cancellation via WhatsApp.
* Sync bookings with a calendar system.
* Multi-language support.