# wellness.py
import os
import logging
from openai import OpenAI
from utils import send_whatsapp_list

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# ≤10 rows (WhatsApp list limit)
TOPIC_ROWS = [
    {"id": "WELLNESS_CORE",      "title": "Core Strength"},
    {"id": "WELLNESS_BACK",      "title": "Lower Back Care"},
    {"id": "WELLNESS_POSTURE",   "title": "Posture at Desk"},
    {"id": "WELLNESS_STRESS",    "title": "Stress Relief / Breathing"},
    {"id": "WELLNESS_FLEX",      "title": "Flexibility & Mobility"},
    {"id": "WELLNESS_RECOVERY",  "title": "Injury Recovery (general)"},
    {"id": "WELLNESS_BEGINNER",  "title": "Beginner: Where to start?"},
    {"id": "WELLNESS_SENIORS",   "title": "Gentle Pilates for Seniors"},
]

def handle_wellness_message(msg_text: str, sender: str | None = None):
    """
    List-first UX:
    - 'WELLNESS' or 'WELLNESS_MENU' -> show topics list
    - 'WELLNESS_*' ids -> answer that topic
    - anything else (free text) -> treat as a question, answer, then show follow-up list
    """
    code = (msg_text or "").strip().upper()
    logging.info(f"[WELLNESS] input={code} sender={sender}")

    # 1) Show topics menu
    if code in ("WELLNESS", "WELLNESS_MENU"):
        send_whatsapp_list(
            sender,
            header="Wellness Q&A",
            body=("Ask a question any time, or pick a topic below. "
                  "Replies are short, friendly, and practical 🌿"),
            button_id="WELLNESS_MENU",
            options=TOPIC_ROWS + [{"id": "MAIN_MENU", "title": "⬅️ Back to Menu"}],
        )
        return "OK"

    # 2) Topic shortcuts
    if code.startswith("WELLNESS_"):
        topic = _topic_hint(code)
        answer = _answer_with_ai(topic)
        _send_answer_with_followups(sender, answer)
        return "OK"

    # 3) Free-text question
    answer = _answer_with_ai(msg_text)
    _send_answer_with_followups(sender, answer)
    return "OK"

def _send_answer_with_followups(sender: str, answer: str):
    """After answering, offer more topics / booking / menu as a list."""
    send_whatsapp_list(
        sender,
        header="Wellness Answer",
        body=answer,
        button_id="WELLNESS_AFTER_ANSWER",
        options=[
            {"id": "WELLNESS_MENU", "title": "More Wellness Topics"},
            {"id": "BOOK",          "title": "📅 Book a Class"},
            {"id": "MAIN_MENU",     "title": "⬅️ Back to Menu"},
        ],
    )

def _topic_hint(code: str) -> str:
    """Map topic id to a short, helpful user prompt."""
    mapping = {
        "WELLNESS_CORE":     "Core & Mobility.",
        "WELLNESS_BACK":     "Ease lower-back tightness.",
        "WELLNESS_POSTURE":  "Posture Focus.",
        "WELLNESS_STRESS":   "Stress Relief.",
        "WELLNESS_FLEX":     "Offer simple flexibility ideas.",
        "WELLNESS_RECOVERY": "Returning after minor strains.",
        "WELLNESS_BEGINNER": "Total beginner start Pilates.",
        "WELLNESS_SENIORS":  "Seniors (Gentle)",
    }
    return mapping.get(code, "Share two short, safe Pilates wellness tips.")

def _answer_with_ai(prompt: str) -> str:
    """Call OpenAI for a concise, warm answer."""
    try:
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a friendly Pilates & wellness coach for PilatesHQ. "
                    "Keep answers concise (3–5 short lines), practical, and positive. "
                    "Use plain language, avoid medical claims, and add 1–2 gentle emojis."
                ),
            },
            {"role": "user", "content": prompt},
        ]
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=180,
            temperature=0.6,
        )
        text = (resp.choices[0].message.content or "").strip()
        logging.info("[WELLNESS] answer_sent")
        return text or "Here are a couple of simple, safe tips to get you started. 🌿"
    except Exception as e:
        logging.error(f"[WELLNESS] OpenAI error: {e}", exc_info=True)
        return "Sorry, I’m having a moment. Please try again shortly. 🌸"
