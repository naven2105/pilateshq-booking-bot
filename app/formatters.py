# formatters.py
#Keeps data retrieval (crud.py) separate from user communication (formatters.py).
#Ensures consistent tone (friendly WhatsApp messages with emojis).
#Easy to update formatting without touching DB queries.

"""
Response Formatter
------------------
Takes structured query results (dicts/lists) and converts them into
friendly WhatsApp-ready messages for clients and admins.
"""

from typing import List, Dict


# 🟢 Booking Management

def format_next_lesson(lesson: Dict) -> str:
    if not lesson:
        return "📌 You don’t have any upcoming lessons booked."
    return f"📌 Your next lesson is on *{lesson['date']}* at *{lesson['time']}*."


def format_sessions_this_week(sessions: List[Dict]) -> str:
    if not sessions:
        return "📌 You have no lessons booked for this week."
    lines = [f"- {s['date']} at {s['time']} ({s['status']})" for s in sessions]
    return "📅 Here are your lessons this week:\n" + "\n".join(lines)


def format_weekly_schedule(sessions: List[Dict]) -> str:
    if not sessions:
        return "📅 No studio sessions scheduled for the coming week."
    lines = [f"- {s['date']} at {s['time']} (Capacity {s['capacity']}, {s['status']})" for s in sessions]
    return "📅 Studio schedule for this week:\n" + "\n".join(lines)


# 🔵 Attendance & Participation

def format_session_attendees(names: List[str]) -> str:
    if not names:
        return "👥 No clients booked for this session yet."
    return "👥 Clients in this session:\n" + "\n".join([f"- {n}" for n in names])


def format_lessons_left(count: int) -> str:
    return f"🎟 You have *{count}* lessons left this month."


def format_clients_for_time(names: List[str], time: str, date: str) -> str:
    if not names:
        return f"📌 No clients booked for {date} at {time}."
    return f"👥 Clients booked for {date} at {time}:\n" + "\n".join([f"- {n}" for n in names])


def format_clients_today(count: int) -> str:
    return f"📌 There are *{count}* clients booked for today."


def format_cancellations(cancellations: List[Dict]) -> str:
    if not cancellations:
        return "❌ No cancellations today."
    lines = [f"- {c['client']} (was {c['date']} {c['time']})" for c in cancellations]
    return "❌ Today’s cancellations:\n" + "\n".join(lines)


def format_clients_without_bookings(names: List[str]) -> str:
    if not names:
        return "✅ All clients have bookings this week."
    return "⚠️ Clients with no bookings this week:\n" + "\n".join([f"- {n}" for n in names])


def format_weekly_recap(sessions: List[Dict]) -> str:
    if not sessions:
        return "📊 No sessions found in the last 7 days."
    lines = [f"- {s['date']} at {s['time']} → {s['count']} booked" for s in sessions]
    return "📊 Weekly Recap:\n" + "\n".join(lines)


# 🟠 Client Lookup (Admin)

def format_client_sessions(sessions: List[Dict], client_name: str) -> str:
    if not sessions:
        return f"📌 No confirmed sessions found for {client_name}."
    lines = [f"- {s['date']} at {s['time']}" for s in sessions]
    return f"📌 Sessions for {client_name}:\n" + "\n".join(lines)


def format_hours_until(hours: float) -> str:
    if hours <= 0:
        return "📌 No lessons remaining today."
    return f"⏳ Next lesson starts in *{hours}* hours."


# 🟣 Pricing & Services

def format_service_price(service: str, price: float) -> str:
    return f"💰 The price for {service} is R{price:.2f}."


# 🟤 General Information

def format_today_date(today: str) -> str:
    return f"📅 Today’s date is {today}."


def format_current_time(now: str) -> str:
    return f"⏰ Current time is {now}."


def format_studio_address(address: str) -> str:
    return f"📍 Studio address: {address}"


def format_studio_rules(rules: str) -> str:
    return "📖 Studio Rules:\n" + rules
