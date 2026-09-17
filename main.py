import os
import datetime
import time
import random
import re
import smtplib
import requests
import feedparser
import asyncio
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from google import genai

# Import podcast audio and RSS update functions
from generate_audio import extract_text_from_html, create_podcast_audio  # <--- ADD THIS
from update_feed import update_podcast_rss  # <--- ADD THIS

# Try loading pandas for reading Excel files
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

# Load environment variables
load_dotenv(override=True)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

# Fallback email recipients from .env if recipients.xlsx is absent
ENV_RECIPIENT_EMAILS = [e.strip() for e in os.getenv("RECIPIENT_EMAILS", "").split(",") if e.strip()]

# Global & Regional Strategic Feeds
RSS_FEEDS = [
    # Global & Western Outlets
    "http://feeds.bbci.co.uk/news/world/rss.xml",                # BBC World News
    "https://rss.dw.com/rdf/rss-en-world",                       # Deutsche Welle (DW)
    "https://thediplomat.com/feed/",                            # The Diplomat (Indo-Pacific/Asia)
    "https://www.aljazeera.com/xml/rss/all.xml",                # Al Jazeera English
    "https://www.theguardian.com/world/rss",                    # The Guardian World

    # South Asian Outlets
    "https://indianexpress.com/section/world/feed/",            # The Indian Express World
    "https://www.thehindu.com/news/international/feeder/default.rss", # The Hindu International
    "https://www.hindustantimes.com/feeds/rss/world-news/rssfeed.xml",# Hindustan Times World
    "https://kathmandupost.com/rss",                            # Kathmandu Post (Nepal & Regional)
    "https://tribune.com.pk/feed/china",                        # Express Tribune Pakistan

    # Chinese & Asia-Pacific Regional Feeds
    "https://www.scmp.com/rss/92/feed",                         # SCMP China/Diplomacy
    "https://www.zaobao.com.sg/rss/realtime/china",             # Lianhe Zaobao China
    "https://www.zaobao.com.sg/rss/realtime/world",             # Lianhe Zaobao World
    "https://www.globaltimes.cn/rss/outbound.xml"               # Global Times
]

# Geopolitical, Defense, and Security Keywords
IR_KEYWORDS = [
    "geopolitics", "security", "defense", "military", "diplomacy", "foreign policy",
    "china", "beijing", "xi jinping", "pla", "taiwan", "south china sea", "indo-pacific",
    "india", "delhi", "himalayas", "border", "nepal", "pakistan", "cpec", "sri lanka",
    "us-china", "sanctions", "trade war", "tariff", "quad", "nato", "ukraine", "russia",
    "外交", "安全", "军事", "制裁", "主权", "南亚", "印度", "中美"
]

def load_recipients(excel_path="recipients.xlsx"):
    """Loads email recipients from an Excel file, falling back to .env if not found."""
    if os.path.exists(excel_path):
        if not PANDAS_AVAILABLE:
            print("⚠️ 'recipients.xlsx' found, but pandas is not installed. Run 'pip install pandas openpyxl'. Falling back to .env.")
            return ENV_RECIPIENT_EMAILS

        try:
            df = pd.read_excel(excel_path)
            df.columns = [str(col).strip().lower() for col in df.columns]
            if 'email' in df.columns:
                emails = df['email'].dropna().astype(str).str.strip().tolist()
                valid_emails = [e for e in emails if "@" in e and "." in e]
                print(f" Loaded {len(valid_emails)} recipient emails from {excel_path}.")
                return valid_emails
            else:
                print(f"⚠️ Column 'email' not found in {excel_path}. Falling back to .env.")
        except Exception as e:
            print(f"⚠️ Error reading {excel_path}: {e}. Falling back to .env.")
    
    print(f" Loaded {len(ENV_RECIPIENT_EMAILS)} recipient email(s) from .env.")
    return ENV_RECIPIENT_EMAILS

def fetch_recent_news():
    """Fetches articles published within the last 24 hours with source diversity rules."""
    cutoff_time = time.time() - (24 * 3600)
    relevant_articles = []
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/rss+xml, application/xml, text/xml, */*"
    }

    for feed_url in RSS_FEEDS:
        try:
            print(f"Checking: {feed_url} ...")
            response = requests.get(feed_url, headers=headers, timeout=8)
            if response.status_code != 200:
                print(f"  Skipped (HTTP {response.status_code})")
                continue

            feed = feedparser.parse(response.content)
            feed_title = feed.feed.get("title", "Global Outlet").replace(" - World", "").replace(" RSS Feed", "")
            feed_count = 0
            
            for entry in feed.entries:
                published_parsed = entry.get("published_parsed") or entry.get("updated_parsed")
                
                if published_parsed:
                    entry_time = time.mktime(published_parsed)
                    if entry_time < cutoff_time:
                        continue
                else:
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
                print(f"  Collected {feed_count} story/stories from [{feed_title}]")

        except Exception as e:
            print(f"  Failed: {e}")

    return relevant_articles

def generate_ai_digest(articles):
    """Synthesizes news into an executive briefing with closing and opt-out details."""
    if not articles:
        return "<p style='font-family:sans-serif;'>No critical geopolitical security developments detected across monitored sources in the last 24 hours.</p>"

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

    prompt = f"""
    You are an intelligence analyst editing "The Daily Geopolitics Monitor". Your audience includes security experts, foreign policy analysts, diplomats, and risk strategists.

    Input dataset collected over the past 24 hours:
    {articles_text}

    Task:
    Synthesize these entries into a modern, executive daily newsletter using RAW HTML with inline CSS.

    Design & Structure Requirements:
    1. Preheader: Add a hidden preview div at the very top:
       <div style="display:none;font-size:1px;color:#333333;line-height:1px;max-height:0px;max-width:0px;opacity:0;overflow:hidden;">
         Today's key geopolitical developments, security briefings, and strategic updates across global powers.
       </div>

    2. Container: Outer wrapper with max-width: 680px, centered, background #ffffff, font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif.

    3. Header Bar: Dark Slate Blue background (#0f172a), white text, title "THE DAILY GEOPOLITICS MONITOR", subtitle "Global Security, Strategic Competition & Regional Dynamics".

    4. Executive Briefing Card (Light gray container #f8fafc with a left accent border #2563eb, padding: 16px):
       - 3-sentence high-level summary of today's key geopolitical posture across major powers.
       - 1-sentence "Immediate Takeaway" for policy analysts.

    5. Three Thematic Sections (Include section header dividers):
       - <h3>Major Power Competition & Global Security</h3> (US, EU, NATO, Russia, China tensions)
       - <h3>South Asia & Strategic Regional Dynamics</h3> (India-China border, Nepal, Pakistan, Sri Lanka, Indian Ocean Security)
       - <h3>Geo-economics, Defense & Maritime Strategy</h3> (Supply chain shifts, sanctions, naval activity, trade)

    Item Formatting Rules:
    - Item Headline: Bold, font size 15px, color #1e293b.
    - Bullet Points: 2-3 concise bullets focusing on *core facts, official rhetoric, and strategic impact*.
    - Source Tag: Format cleanly at the end of each entry as: 
      <a href="URL" style="color:#2563eb; text-decoration:none; font-weight:600; font-size:12px;">[Source: Outlet Name] →</a>

    6. Desk Sign-off:
       Add a professional closing:
       <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #e2e8f0; color: #334155;">
         <p style="margin: 0; font-weight: 600; font-size: 14px;">Warm regards,</p>
         <p style="margin: 4px 0 0 0; font-weight: 700; font-size: 15px; color: #0f172a;">Daily Dispatch Desk</p>
         <p style="margin: 2px 0 0 0; font-size: 12px; color: #64748b;">The Daily Geopolitics Monitor</p>
       </div>

    7. Footer & Unsubscribe Disclaimer:
       <div style="margin-top: 24px; padding-top: 12px; text-align: center; font-size: 11px; color: #94a3b8; line-height: 1.5;">
         <p style="margin: 0;">You are receiving this automated intelligence briefing because you are subscribed to <em>The Daily Geopolitics Monitor</em>.</p>
         <p style="margin: 4px 0 0 0;">If you wish to opt out of future dispatches, simply reply to this email or write to <a href="mailto:dailydispatchdesk@gmail.com" style="color:#64748b; text-decoration:underline;">dailydispatchdesk@gmail.com</a>.</p>
       </div>

    Instructions:
    - Output ONLY raw HTML. Do NOT use markdown ```html code blocks.
    """

    client = genai.Client(api_key=GEMINI_API_KEY)
    preferred_models = [
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        "gemini-2.5-flash-latest",
        "gemini-1.5-flash"
    ]

    models_to_try = ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-1.5-flash-latest"]
    
    prompt = f"Analyze these articles and produce an executive briefing in HTML:\n{articles}"
    
    for model_name in models_to_try:
        for attempt in range(1, 4):
            try:
                print(f"Generating briefing with model: {model_name} (Attempt {attempt})...")
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt
                )
                if response.text:
                    return response.text
            except Exception as e:
                print(f" Model '{model_name}' attempt {attempt} failed: {e}")
                time.sleep(2 * attempt)  # Wait 2s, 4s, 6s before retrying 503s
                
    raise RuntimeError("All Gemini models failed after retries.")

def strip_html_tags(text):
    """Strips HTML tags to create a clean text-only fallback payload."""
    clean = re.compile('<.*?>')
    return re.sub(clean, '', text)

def send_emails_individually(html_content, recipients):
    """Sends individual emails using Dual-MIME payload and random delays to minimize spam flags."""
    today_str = datetime.date.today().strftime('%B %d, %Y')
    clean_user = GMAIL_USER.strip() if GMAIL_USER else ""
    clean_pwd = GMAIL_APP_PASSWORD.replace(" ", "").strip() if GMAIL_APP_PASSWORD else ""

    if not clean_user or not clean_pwd:
        print("\n❌ CRITICAL ERROR: GMAIL_USER or GMAIL_APP_PASSWORD missing in .env!")
        return

    if not recipients:
        print("❌ No recipients specified. Aborting dispatch.")
        return

    print(f"\n📧 Dispatching newsletter to {len(recipients)} recipient(s)...")

    # Generate plain-text alternative to improve deliverability score
    plain_text_content = strip_html_tags(html_content)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(clean_user, clean_pwd)

            for idx, recipient in enumerate(recipients, 1):
                msg = MIMEMultipart("alternative")
                msg["Subject"] = f"The Daily Geopolitics Monitor: Global Security & Strategy ({today_str})"
                msg["From"] = f"Daily Dispatch Desk <{clean_user}>"
                msg["To"] = recipient
                msg["Reply-To"] = clean_user

                # Attach Plain Text first, then HTML (MIME standard for anti-spam)
                part_text = MIMEText(plain_text_content, "plain")
                part_html = MIMEText(html_content, "html")
                msg.attach(part_text)
                msg.attach(part_html)

                try:
                    server.sendmail(clean_user, recipient, msg.as_string())
                    print(f"  [{idx}/{len(recipients)}] Delivered to: {recipient}")
                except Exception as send_err:
                    print(f"  ❌ Failed delivery for {recipient}: {send_err}")

                # Random pause between 3.0 and 6.0 seconds to prevent bot behavior flags
                delay = random.uniform(3.0, 6.0)
                time.sleep(delay)

        print("\n Delivery process complete!")
    except Exception as e:
        print(f"❌ SMTP Connection Error: {e}")

if __name__ == "__main__":
    print("--- STARTING GEOPOLITICS MONITOR PIPELINE ---")
    
    # 1. Load target recipients
    recipients = load_recipients("recipients.xlsx")
    
    # 2. Aggregating news
    print("\n1. Aggregating multi-source global news feeds...")
    articles = fetch_recent_news()
    print(f"\nTotal: Collected {len(articles)} relevant stories from diverse outlets.")

    # 3. Generate summary
    print("\n2. Generating executive intelligence digest...")
    digest_html = generate_ai_digest(articles)

# ---------------------------------------------------------
    # NEW: 4. Generate Podcast Audio & Update RSS Feed
    # ---------------------------------------------------------
    print("\n3. Generating audio podcast episode...")
    try:
        spoken_text = extract_text_from_html(digest_html)
        asyncio.run(create_podcast_audio(spoken_text, "latest_episode.mp3"))
        update_podcast_rss()
        print(" Podcast audio episode and RSS feed successfully updated!")
    except Exception as audio_err:
        print(f"⚠️ Audio podcast generation failed: {audio_err}")
    # ---------------------------------------------------------

    # 5. Send emails
    print("\n3. Dispatching briefing emails...")
    send_emails_individually(digest_html, recipients)
    print("--- PIPELINE COMPLETE ---")