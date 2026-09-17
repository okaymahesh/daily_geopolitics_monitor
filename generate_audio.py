import asyncio
import edge_tts
from bs4 import BeautifulSoup

def extract_text_from_html(html_content):
    """Strips HTML tags so only clean, spoken text remains."""
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Remove hidden preheaders, styles, or scripts
    for elem in soup.find_all(['style', 'script', 'head']):
        elem.decompose()
    
    text = soup.get_text(separator=' ')
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return " ".join(lines)

async def create_podcast_audio(text_content, output_filename="latest_episode.mp3"):
    """Converts text into an MP3 file using Microsoft Edge's free neural voice."""
    # Options: 'en-US-ChristopherNeural' (Male) or 'en-US-AvaNeural' (Female)
    VOICE = "en-US-ChristopherNeural"
    communicate = edge_tts.Communicate(text_content, VOICE)
    await communicate.save(output_filename)
    print(f"✅ Audio file successfully generated: {output_filename}")

if __name__ == "__main__":
    # Quick local test
    sample_text = "Welcome to the Daily Geopolitics Monitor audio briefing."
    asyncio.run(create_podcast_audio(sample_text))