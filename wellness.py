import os, logging
from openai import OpenAI
from utils import send_whatsapp_list

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# Short titles (≤24 chars)
TOPIC_ROWS = [
    {"id": "WELLNESS_CORE",     "title": "Core & Mobility",    "description": "Safe starter tips"},
    {"id": "WELLNESS_BACK",     "title": "Lower Back Care",    "description": "Gentle relief ideas"},
    {"id": "WELLNESS_POSTURE",  "title": "Desk Posture",       "description": "Micro-mobility moves"},
    {"id": "WELLNESS_STRESS",   "title": "Stress Relief",      "description": "Breathing & calm"},
    {"id": "WELLNESS_FLEX",     "title": "Flex & Mobility",    "description": "Hips & hamstrings"},
    {"id": "WELLNESS_RECOV",    "title": "Recovery (General)", "description": "Ease back in safely"},
    {"id": "WELLNESS_BEGIN",    "title": "Beginner Start",     "description": "Where to begin"},
    {"id": "WELLNESS_SENIORS",  "title": "Seniors (Gentle)",   "description": "Joint-friendly"},
]

def handle_wellness_message(msg_text: str, sender: str | None = None):
    code = (msg_text or "").strip().upper()
    logging.info(f"[WELLNESS] input={code} sender={sender}")

    # Show topics
    if code in ("WELLNESS", "WELLNESS_MENU"):
        send_whatsapp_list(
            sender, "Wellness Q&A",
            "Ask a question any time, or pick a topic below. Replies are short, friendly, and practical 🌿",
            "WELLNESS_MENU",
            TOPIC_ROWS + [{"id": "MAIN_MENU", "title": "⬅️ Back to Menu"}]
        )
        return "OK"

    # Topic paths
    if code.startswith("WELLNESS_"):
        prompt = _topic_prompt(code)
        answer = _ai_answer(prompt)
        _followup(sender, answer)
        return "OK"

    # Free text question
    answer = _ai_answer(msg_text)
    _followup(sender, answer)
    return "OK"

def _followup(sender: str, answer: str):
    send_whatsapp_list(
        sender, "Wellness Answer", answer, "WELLNESS_AFTER",
        [
            {"id": "WELLNESS_MENU", "title": "More Topics"},
            {"id": "BOOK",          "title": "📅 Book a Class"},
            {"id": "MAIN_MENU",     "title": "⬅️ Back to Menu"},
        ]
    )

def _topic_prompt(code: str) -> str:
    mapping = {
        "WELLNESS_CORE":    "Give 2–3 safe core-strength tips for Pilates beginners.",
        "WELLNESS_BACK":    "Gentle Pilates-based tips to ease lower-back tightness.",
        "WELLNESS_POSTURE": "Desk-posture tips plus 2 micro-mobility moves.",
        "WELLNESS_STRESS":  "Breathing + short calming routine for stress relief.",
        "WELLNESS_FLEX":    "Simple flexibility ideas for hips and hamstrings.",
        "WELLNESS_RECOV":   "Safety-first advice for returning after minor strains.",
        "WELLNESS_BEGIN":   "How should a total beginner start Pilates?",
        "WELLNESS_SENIORS": "Gentle, joint-friendly Pilates suggestions for seniors.",
    }
    return mapping.get(code, "Share two short, safe Pilates wellness tips.")

def _ai_answer(prompt: str) -> str:
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role":"system","content":(
                    "You are a friendly Pilates & wellness coach for PilatesHQ. "
                    "Keep answers concise (3–5 short lines), practical and positive. "
                    "Avoid medical claims; add 1–2 gentle emojis."
                )},
                {"role":"user","content": prompt},
            ],
            max_tokens=180,
            temperature=0.6,
        )
        txt = (resp.choices[0].message.content or "").strip()
        logging.info("[WELLNESS] answer_sent")
        return txt or "Here are a couple of simple, safe tips to get you started. 🌿"
    except Exception as e:
        logging.error(f"[WELLNESS] OpenAI error: {e}", exc_info=True)
        return "Sorry, I’m having a moment. Please try again shortly. 🌸"
