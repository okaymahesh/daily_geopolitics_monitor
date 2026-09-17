from datetime import datetime

def update_podcast_rss():
    BASE_URL = "https://okaymahesh.github.io/daily_geopolitics_monitor"
    pub_date = datetime.now().strftime('%a, %d %b %Y %H:%M:%S GMT')
    guid_date = datetime.now().strftime('%Y%m%d')

    rss_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>The Daily Geopolitics Monitor</title>
    <link>{BASE_URL}</link>
    <language>en-us</language>
    <itunes:author>Daily Dispatch Desk</itunes:author>
    <itunes:summary>Daily automated executive briefing on global security, strategic competition, and regional dynamics.</itunes:summary>
    <itunes:category text="News">
      <itunes:category text="Daily News"/>
    </itunes:category>
    <itunes:explicit>false</itunes:explicit>
    <itunes:image href="{BASE_URL}/cover.jpg"/>
    
    <item>
      <title>Daily Geopolitics Briefing - {datetime.now().strftime('%b %d, %Y')}</title>
      <itunes:author>Daily Dispatch Desk</itunes:author>
      <itunes:summary>Today's executive geopolitical intelligence summary.</itunes:summary>
      <enclosure url="{BASE_URL}/latest_episode.mp3" length="1000000" type="audio/mpeg"/>
      <guid>{BASE_URL}/latest_episode.mp3?v={guid_date}</guid>
      <pubDate>{pub_date}</pubDate>
    </item>
  </channel>
</rss>
"""
    with open("feed.xml", "w", encoding="utf-8") as f:
        f.write(rss_content)
    print("✅ Updated podcast RSS feed: feed.xml")

if __name__ == "__main__":
    update_podcast_rss()