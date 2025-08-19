import os
import logging
from openai import OpenAI

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

def handle_wellness_message(msg_text: str, sender: str | None = None) -> str:
    """Short, warm Pilates/wellness tips. Logs Q/A for lightweight analytics."""
    try:
        logging.info(f"[WELLNESS] q -> {sender} | {str(msg_text)[:80]}")
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a friendly Pilates & wellness coach. "
                        "Keep answers short, supportive, and practical. "
                        "Add 1–2 uplifting emojis (🌸💪🧘✨😊). "
                        "Offer 1–2 quick tips, avoid long paragraphs."
                    )
                },
                {"role": "user", "content": msg_text},
            ],
            max_tokens=150,
        )
        answer = resp.choices[0].message.content.strip()
        logging.info(f"[WELLNESS] a_sent -> {sender}")
        return answer
    except Exception as e:
        logging.error(f"[WELLNESS] OpenAI error: {e}", exc_info=True)
        return "Sorry, I’m having trouble right now. Please try again in a bit. 🌸"
