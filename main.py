import os
import datetime
import time
import re
import smtplib
import requests
import feedparser
import asyncio
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from dotenv import load_dotenv
from google import genai

# Import podcast audio and RSS update functions
from generate_audio import extract_text_from_html, create_podcast_audio

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

load_dotenv(override=True)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

ENV_RECIPIENT_EMAILS = [e.strip() for e in os.getenv("RECIPIENT_EMAILS", "").split(",") if e.strip()]

RSS_FEEDS = [
    "http://feeds.bbci.co.uk/news/world/rss.xml",
    "https://rss.dw.com/rdf/rss-en-world",
    "https://thediplomat.com/feed/",
    "https://www.aljazeera.com/xml/rss/all.xml",
    "https://www.theguardian.com/world/rss",
    "https://indianexpress.com/section/world/feed/",
    "https://www.thehindu.com/news/international/feeder/default.rss",
    "https://kathmandupost.com/rss",
    "https://www.scmp.com/rss/92/feed"
]

IR_KEYWORDS = [
    "geopolitics", "security", "defense", "military", "diplomacy", "foreign policy",
    "china", "beijing", "xi jinping", "pla", "taiwan", "south china sea", "indo-pacific",
    "india", "delhi", "himalayas", "border", "nepal", "pakistan", "cpec", "sri lanka",
    "us-china", "sanctions", "trade war", "tariff", "quad", "nato", "ukraine", "russia"
]

LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.png")
LOGO_CONTENT_ID = "faultline-logo"

def load_recipients(excel_path="recipients.xlsx"):
    if os.path.exists(excel_path):
        if not PANDAS_AVAILABLE:
            print("⚠️ 'recipients.xlsx' found, but pandas is not installed. Falling back to .env.")
            return ENV_RECIPIENT_EMAILS

        try:
            df = pd.read_excel(excel_path)
            df.columns = [str(col).strip().lower() for col in df.columns]
            if 'email' in df.columns:
                emails = df['email'].dropna().astype(str).str.strip().tolist()
                valid_emails = [e for e in emails if "@" in e and "." in e]
                print(f" Loaded {len(valid_emails)} recipient email(s) from {excel_path}.")
                return valid_emails
        except Exception as e:
            print(f"⚠️ Error reading {excel_path}: {e}. Falling back to .env.")
    
    print(f" Loaded {len(ENV_RECIPIENT_EMAILS)} recipient email(s) from .env.")
    return ENV_RECIPIENT_EMAILS

def sanitize_url(raw_url):
    match = re.search(r'https?://[^\s\>\]\)]+', str(raw_url))
    if match:
        return match.group(0).rstrip('"\'()[]><')
    return raw_url.strip()

def fetch_recent_news():
    cutoff_time = time.time() - (24 * 3600)
    relevant_articles = []
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/rss+xml, application/xml, text/xml, */*"
    }

    for raw_feed_url in RSS_FEEDS:
        feed_url = sanitize_url(raw_feed_url)
        try:
            print(f"Checking: {feed_url} ...")
            response = requests.get(feed_url, headers=headers, timeout=8)
            if response.status_code != 200:
                print(f"   Skipped (HTTP {response.status_code})")
                continue

            feed = feedparser.parse(response.content)
            feed_title = feed.feed.get("title", "Global Outlet").replace(" - World", "").replace(" RSS Feed", "")
            feed_count = 0
            
            for entry in feed.entries:
                published_parsed = entry.get("published_parsed") or entry.get("updated_parsed")
                if published_parsed:
                    if time.mktime(published_parsed) < cutoff_time:
                        continue

                title = entry.get("title", "")
                summary = entry.get("summary", "")
                content_text = f"{title} {summary}".lower()

                if any(keyword in content_text for keyword in IR_KEYWORDS):
                    relevant_articles.append({
                        "title": title,
                        "link": entry.get("link", ""),
                        "summary": summary,
                        "source": feed_title
                    })
                    feed_count += 1
                    if feed_count >= 3:
                        break

            if feed_count > 0:
                print(f"   Collected {feed_count} story/stories from [{feed_title}]")

        except Exception as e:
            print(f"   Failed: {e}")

    return relevant_articles

def clean_html_output(raw_html):
    """Remove an optional Markdown code fence around generated HTML."""
    cleaned = (raw_html or "").strip()
    cleaned = re.sub(r"^```(?:html)?\s*", "", cleaned, count=1, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```\s*$", "", cleaned, count=1)
    return cleaned.strip()

def generate_ai_digest(articles):
    if not articles:
        return "<p style='font-family:sans-serif;'>No critical developments detected in the last 24 hours.</p>"

    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY missing in .env file.")

    source_counts = {}
    balanced_articles = []
    for art in articles:
        src = art['source']
        source_counts[src] = source_counts.get(src, 0) + 1
        if source_counts[src] <= 2:
            balanced_articles.append(art)

    articles_text = ""
    for idx, art in enumerate(balanced_articles[:22], 1):
        articles_text += f"\nArticle {idx}:\nSource: {art['source']}\nTitle: {art['title']}\nSnippet: {art['summary']}\nURL: {art['link']}\n"

    user_prompt = f"""
Input dataset collected over the past 24 hours:
{articles_text}

Task:
Synthesize these entries into a modern daily newsletter using RAW HTML with inline CSS.

Design & Structure Requirements:
1. Container: Outer wrapper max-width 680px, centered, background #ffffff, font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif.
2. Header Section:
   - Use a clean white background with 20px 24px padding.
   - The header must contain only this placeholder as its branding row:
     `<div id="HEADER_LOGO_PLACEHOLDER"></div>`
   - Do not add a separate FAULTLINE logo, institution name, or monitor title;
     these will be inserted into the placeholder after generation.
3. Executive Summary Card (#f8fafc with left accent border 4px #2563eb, padding 16px, border-radius 4px): 3-sentence high-level overview and 1-sentence "Key Takeaway".
4. Three Core Sections:
   - <h3>Major Power Competition & Global Security</h3>
   - <h3>South Asia & Strategic Regional Dynamics</h3>
   - <h3>Geo-economics, Defense & Maritime Strategy</h3>
5. Item Format: Bold headline (15px), 2-3 concise bullet points, and source tag <a href="URL">[Source: Outlet Name] →</a>.
6. Footer: "Faultline Institute | Daily Geopolitics Monitor", recipient privacy note, and unsubscribe notice.

CRITICAL REQUIREMENT: Output ONLY raw HTML. Do NOT include markdown code blocks like ```html.
"""

    client = genai.Client(api_key=GEMINI_API_KEY)
    
    models_to_try = [
        "gemini-3.8-flash",
        "gemini-3.5-flash"
    ]

    raw_html_result = ""
    model_errors = {}
    for model in models_to_try:
        for attempt in range(4):
            try:
                print(f"Generating briefing using Gemini ({model}) [Attempt {attempt + 1}]...")
                response = client.models.generate_content(
                    model=model,
                    contents=user_prompt
                )
                if not response.text or not response.text.strip():
                    raise RuntimeError(f"{model} returned an empty response")
                raw_html_result = clean_html_output(response.text)
                if raw_html_result:
                    break
            except Exception as e:
                model_errors[model] = str(e)
                error_text = str(e).upper()
                if any(marker in error_text for marker in ("400", "401", "403", "404", "INVALID_ARGUMENT", "UNAUTHENTICATED", "PERMISSION_DENIED", "NOT_FOUND")):
                    print(f"⚠️ Non-retryable Gemini error for {model} ({e}). Trying the next model.")
                    break
                wait_time = (attempt + 1) * 4
                print(f"⚠️ Model {model} attempt {attempt + 1} failed ({e}). Retrying in {wait_time}s...")
                time.sleep(wait_time)
        if raw_html_result:
            break

    if not raw_html_result:
        details = " | ".join(
            f"{model}: {error}" for model, error in model_errors.items()
        ) or "Gemini returned no usable HTML response."
        raise RuntimeError(f"Gemini briefing generation failed. Details: {details}")

    logo_tag = f'''<table role="presentation" width="100%" border="0" cellpadding="0" cellspacing="0" bgcolor="#ffffff"
        style="width:100%;border-collapse:collapse;background-color:#ffffff !important;color:#0f172a;">
      <tr>
        <td width="148" valign="middle" bgcolor="#ffffff"
          style="width:148px;padding:6px;background-color:#ffffff !important;vertical-align:middle;text-align:center;">
          <img src="cid:{LOGO_CONTENT_ID}" width="128" alt="Faultline"
            style="display:block;width:128px;max-width:100%;height:auto;background-color:#ffffff;border:0;outline:none;text-decoration:none;">
        </td>
        <td valign="middle" bgcolor="#ffffff"
          style="padding:12px 16px;background-color:#ffffff !important;vertical-align:middle;font-family:Arial,Helvetica,sans-serif;border-left:1px solid #dbeafe;">
          <div style="margin:0 0 7px;color:#334155;font-size:13px;line-height:1.4;font-weight:500;">
            Institute for Statecraft, Technology and Society
          </div>
          <div style="margin:0;color:#1d4ed8;font-size:22px;line-height:1.25;font-weight:700;letter-spacing:.3px;">
            Daily Geopolitics Monitor
          </div>
        </td>
      </tr>
    </table>'''
    placeholder_pattern = (
        r'<div\b(?=[^>]*\bid\s*=\s*["\']HEADER_LOGO_PLACEHOLDER["\'])'
        r'[^>]*>\s*</div\s*>'
    )
    raw_html_result, placeholder_count = re.subn(
        placeholder_pattern, logo_tag, raw_html_result, count=1, flags=re.IGNORECASE
    )
    if placeholder_count == 0:
        # Preserve the same branding if the model omitted its header placeholder.
        body_open = re.search(r"<body\b[^>]*>", raw_html_result, flags=re.IGNORECASE)
        if body_open:
            raw_html_result = (
                raw_html_result[:body_open.end()]
                + logo_tag
                + raw_html_result[body_open.end():]
            )
        else:
            raw_html_result = logo_tag + raw_html_result

    return raw_html_result

def strip_html_tags(text):
    return re.sub(r'<.*?>', '', text)

def send_emails_individually(html_content, recipients):
    today_str = datetime.date.today().strftime('%B %d, %Y')
    clean_user = GMAIL_USER.strip() if GMAIL_USER else ""
    clean_pwd = GMAIL_APP_PASSWORD.replace(" ", "").strip() if GMAIL_APP_PASSWORD else ""

    if not clean_user or not clean_pwd or not recipients:
        print("❌ Invalid sender config or recipients list. Aborting email dispatch.")
        return

    print(f"\n📧 Dispatching newsletter to {len(recipients)} recipient(s)...")

    plain_text_content = strip_html_tags(html_content)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(clean_user, clean_pwd)

            for idx, recipient in enumerate(recipients, 1):
                # The related container binds the HTML's cid: image to this message.
                msg = MIMEMultipart("related")
                msg["Subject"] = f"Faultline Geopolitics Monitor: Daily News Brief ({today_str})"
                msg["From"] = f"Faultline Dispatch Desk <{clean_user}>"
                msg["To"] = recipient

                alternatives = MIMEMultipart("alternative")
                alternatives.attach(MIMEText(plain_text_content, "plain", "utf-8"))
                alternatives.attach(MIMEText(html_content, "html", "utf-8"))
                msg.attach(alternatives)

                if os.path.isfile(LOGO_PATH):
                    with open(LOGO_PATH, "rb") as logo_file:
                        logo_image = MIMEImage(logo_file.read(), _subtype="png")
                    logo_image.add_header("Content-ID", f"<{LOGO_CONTENT_ID}>")
                    logo_image.add_header("Content-Disposition", "inline", filename="logo.png")
                    msg.attach(logo_image)
                else:
                    print(f"⚠️ Logo file not found; sending without inline logo: {LOGO_PATH}")

                server.sendmail(clean_user, recipient, msg.as_string())
                print(f"   [{idx}/{len(recipients)}] Delivered to: {recipient}")
                time.sleep(1.0)

        print("\n Delivery process complete!")
    except Exception as e:
        print(f"❌ SMTP Connection Error: {e}")

if __name__ == "__main__":
    print("--- STARTING FAULTLINE GEOPOLITICS MONITOR PIPELINE ---")
    recipients = load_recipients("recipients.xlsx")
    
    print("\n1. Aggregating multi-source global news feeds...")
    articles = fetch_recent_news()
    print(f"\nTotal: Collected {len(articles)} relevant stories from diverse outlets.")

    print("\n2. Generating daily news brief...")
    digest_html = generate_ai_digest(articles)

    print("\n3. Generating audio podcast episode...")
    try:
        spoken_text = extract_text_from_html(digest_html)
        asyncio.run(create_podcast_audio(spoken_text, "latest_episode.mp3"))
        print(" Podcast audio episode and RSS feed successfully updated!")
    except Exception as audio_err:
        print(f"⚠️ Audio podcast generation failed: {audio_err}")

    print("\n4. Dispatching briefing emails...")
    send_emails_individually(digest_html, recipients)
    print("--- PIPELINE COMPLETE ---")
