# 🔹 wellness.py (ChatGPT Assistant)
# Uses OPENAI_API_KEY.
# Friendly Pilates & wellness tone.
# Short, supportive tips with emojis 🌸💪🧘✨.
# Replies feel human and warm, not robotic.

from openai import OpenAI
import os

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

def handle_wellness_message(msg_text: str) -> str:
    """
    Handle wellness Q&A by calling OpenAI.
    The assistant speaks like a warm, supportive Pilates coach.
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a friendly Pilates and wellness coach. "
                        "Keep answers short, supportive, and practical. "
                        "Always add 1–2 uplifting emojis (like 🌸💪🧘✨😊) to make it warm and human. "
                        "Avoid sounding too formal or robotic. "
                        "If relevant, give 1–2 quick tips instead of long paragraphs."
                    )
                },
                {"role": "user", "content": msg_text},
            ],
            max_tokens=150,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print("Error with OpenAI wellness assistant:", e)
        return "Sorry, I'm having trouble answering that right now. 🌸"
