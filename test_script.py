"""Quick test: fetch one topic from Google News RSS and resolve real URLs.

Does NOT need a Gemini key or email setup. Run: python test_script.py
"""

from news_report import fetch_topic_news, resolve_real_url

cfg = {"per_topic": 5, "lang": "en-US", "country": "US"}
topic = "artificial intelligence"

print(f"Fetching top {cfg['per_topic']} news for: {topic}\n")
articles = fetch_topic_news(topic, cfg)

for i, a in enumerate(articles, 1):
    real = resolve_real_url(a.link)
    print(f"{i}. {a.title}")
    print(f"   source: {a.source}")
    print(f"   link:   {real}\n")

print(f"Done. {len(articles)} articles fetched.")
