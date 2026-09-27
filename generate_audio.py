import os
import time
import asyncio
import re
import edge_tts
from google import genai
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from update_feed import update_podcast_rss

load_dotenv(override=True)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

def extract_text_from_html(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    for elem in soup.find_all(['style', 'script', 'head']):
        elem.decompose()
    
    text = soup.get_text(separator=' ')
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return " ".join(lines)

def generate_podcast_script(raw_text):
    if not GEMINI_API_KEY:
        print("⚠️ GEMINI_API_KEY missing for podcast script synthesis. Using stripped text.")
        return raw_text

    prompt = f"""
You are a top-tier podcast host producing today's episode of "Faultline Geopolitics Monitor".
Transform the following daily news summary into a natural, engaging 2-minute audio podcast script.

Guidelines:
1. Opening: Warm greeting (e.g., "Welcome back to Faultline Geopolitics Monitor, your daily news brief...").
2. Conversational Flow: Speak in full sentences. Do NOT read URLs, source links, or structural tags.
3. Transitions: Use smooth spoken transitions between topics.
4. Sign-off: Professional closing on behalf of the Faultline Institute.

Raw Newsletter Content:
{raw_text}

Output ONLY the script text to be spoken out loud.
"""

    client = genai.Client(api_key=GEMINI_API_KEY)
    
    models_to_try = [
        "gemini-3.8-flash",
        "gemini-3.5-flash"
    ]

    model_errors = {}
    for model in models_to_try:
        for attempt in range(4):
            try:
                print(f"Generating podcast script using Gemini ({model}) [Attempt {attempt + 1}]...")
                response = client.models.generate_content(
                    model=model,
                    contents=prompt
                )
                script = response.text
                if not script or not script.strip():
                    raise RuntimeError(f"{model} returned an empty response")
                return re.sub(r"\[.*?\]", "", script).strip()
            except Exception as e:
                model_errors[model] = str(e)
                error_text = str(e).upper()
                if any(marker in error_text for marker in ("400", "401", "403", "404", "INVALID_ARGUMENT", "UNAUTHENTICATED", "PERMISSION_DENIED", "NOT_FOUND")):
                    print(f"⚠️ Non-retryable Gemini error for {model} ({e}). Trying the next model.")
                    break
                wait_time = (attempt + 1) * 4
                print(f"⚠️ Model {model} attempt {attempt + 1} failed for podcast script ({e}). Retrying in {wait_time}s...")
                time.sleep(wait_time)

    details = " | ".join(
        f"{model}: {error}" for model, error in model_errors.items()
    ) or "Gemini returned no usable script response."
    print(f"⚠️ Gemini podcast script generation failed ({details}). Falling back to raw text.")
    return raw_text

async def create_podcast_audio(text_content, output_filename="latest_episode.mp3"):
    script = generate_podcast_script(text_content)
    VOICE = "en-US-AndrewMultilingualNeural"
    print(f"Synthesizing audio with Edge TTS [{VOICE}]...")
    
    communicate = edge_tts.Communicate(script, voice=VOICE, rate="-4%", pitch="+0Hz")
    await communicate.save(output_filename)
    update_podcast_rss()
    print(f"✅ Conversational podcast audio generated: {output_filename}")
