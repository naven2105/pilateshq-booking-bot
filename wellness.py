# wellness.py
import os
from openai import OpenAI

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

def handle_wellness_message(msg_text: str) -> str:
    """
    Send wellness/FAQ/general queries to ChatGPT.
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a friendly Pilates and wellness assistant."},
                {"role": "user", "content": msg_text}
            ]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print("OpenAI error:", e)
        return "Sorry, I couldn’t fetch a wellness tip right now."
