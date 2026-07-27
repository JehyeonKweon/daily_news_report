"""Google News RSS fetch helpers."""

from __future__ import annotations

from urllib.parse import quote

import feedparser

from core.models import Article

RSS_FETCH_CAP = 100

# Google News topic ID for cybersecurity (US). Used by 보안 international feed.
SECURITY_INTL_TOPIC_ID = "CAAqIggKIhxDQkFTRHdvSkwyMHZNRE5xWm01NEVnSmxiaWdBUAE"


def build_search_query(base_query: str, days_back: int = 1) -> str:
    """Keywords + Google News when:Nd."""
    query = base_query.strip()
    if days_back > 0:
        query = f"{query} when:{days_back}d"
    return query


def build_rss_search_url(query: str, lang: str, country: str) -> str:
    """Full Google News RSS search URL with URL-encoded query parameters."""
    ceid = f"{country}:{lang.split('-')[0]}"
    return (
        "https://news.google.com/rss/search?"
        f"q={quote(query, safe='')}"
        f"&hl={lang}&gl={country}&ceid={quote(ceid, safe='')}"
    )


def build_rss_topic_url(topic_id: str, lang: str, country: str) -> str:
    """Google News RSS topic/section feed URL."""
    ceid = f"{country}:{lang.split('-')[0]}"
    return (
        f"https://news.google.com/rss/topics/{topic_id}"
        f"?hl={lang}&gl={country}&ceid={quote(ceid, safe='')}"
    )


def build_topic_web_url(topic_id: str, lang: str, country: str) -> str:
    """Human-readable Google News topic page (same feed, not RSS)."""
    ceid = f"{country}:{lang.split('-')[0]}"
    return (
        f"https://news.google.com/topics/{topic_id}"
        f"?hl={lang}&gl={country}&ceid={quote(ceid, safe='')}"
    )


def rss_url_to_topic_web_url(rss_url: str) -> str:
    """Derive topic page URL from a stored RSS topic feed URL."""
    if "/rss/topics/" not in rss_url:
        return ""
    return rss_url.replace("/rss/topics/", "/topics/", 1)


def feed_rss_url(feed: dict) -> str:
    """Resolve the RSS URL for a feed (search or topic mode)."""
    if feed.get("mode") == "topic":
        return build_rss_topic_url(feed["topic_id"], feed["lang"], feed["country"])
    query = build_search_query(feed["query"], feed.get("days_back", 1))
    return build_rss_search_url(query, feed["lang"], feed["country"])


def fetch_rss_entries(url: str, limit: int = RSS_FETCH_CAP) -> list[Article]:
    feed = feedparser.parse(url)
    articles: list[Article] = []
    for entry in feed.entries[:limit]:
        source = ""
        if getattr(entry, "source", None) is not None:
            source = getattr(entry.source, "title", "") or ""
        # feedparser maps RSS <guid> to entry.id
        guid = (getattr(entry, "id", None) or getattr(entry, "guid", None) or "").strip()
        articles.append(
            Article(
                topic="",
                title=getattr(entry, "title", "(no title)"),
                link=getattr(entry, "link", ""),
                source=source,
                published=getattr(entry, "published", ""),
                guid=guid,
            )
        )
    return articles


def fetch_feed_pool(feed: dict) -> list[Article]:
    """Fetch up to RSS_FETCH_CAP items for a feed (full candidate pool)."""
    url = feed_rss_url(feed)
    articles = fetch_rss_entries(url, RSS_FETCH_CAP)
    for article in articles:
        article.topic = feed["label"]
    return articles


def fetch_feed_news(feed: dict, per_topic: int) -> list[Article]:
    """Back-compat helper: return first `per_topic` items from the RSS pool."""
    return fetch_feed_pool(feed)[:per_topic]
