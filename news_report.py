"""Daily news report.

Fetches the top trending news per topic from Google News RSS, summarizes each
article with Google Gemini, and emails a clean HTML report via Outlook/SMTP.

Run:  python news_report.py
Config is read from a .env file (see .env.example).
"""

# 타입 힌트를 위한 임포트 예) list[Article]
from __future__ import annotations

# 필요 라이브러리 임포트
import os
import re
import smtplib
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from urllib.parse import quote_plus

import feedparser
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}


@dataclass
class Article:
    topic: str
    title: str
    link: str
    source: str
    published: str
    summary: str = ""
    title_translated: str = ""


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
def parse_topic(raw: str) -> tuple[str, str]:
    """Split a TOPICS entry into (label, query).

    Syntax: "Label | search query". The label is the clean heading shown in the
    report; the query is what's actually sent to Google News. If no "|" is given,
    the raw text is used for both.
    """
    if "|" in raw:
        label, query = raw.split("|", 1)
        return label.strip(), query.strip()
    text = raw.strip()
    return text, text


def load_config() -> dict:
    load_dotenv()

    topics_raw = os.getenv("TOPICS", "")
    topics = [parse_topic(t) for t in topics_raw.split(",") if t.strip()]
    if not topics:
        sys.exit("No TOPICS configured. Add some to your .env file.")

    cfg = {
        "topics": topics,
        "per_topic": int(os.getenv("NEWS_PER_TOPIC", "10")),
        "lang": os.getenv("NEWS_LANG", "en-US"),
        "country": os.getenv("NEWS_COUNTRY", "US"),
        "gemini_api_key": os.getenv("GEMINI_API_KEY", "").strip(),
        "gemini_model": os.getenv("GEMINI_MODEL", "gemini-flash-latest").strip(),
        "summary_language": os.getenv("SUMMARY_LANGUAGE", "Korean").strip(),
        "require_keywords": [
            k.strip() for k in os.getenv("REQUIRE_KEYWORDS", "").split(",") if k.strip()
        ],
        "dedupe": os.getenv("DEDUPE", "true").strip().lower() in ("1", "true", "yes", "on"),
        "dedupe_threshold": float(os.getenv("DEDUPE_THRESHOLD", "0.5")),
        "smtp_host": os.getenv("SMTP_HOST", "smtp.office365.com"),
        "smtp_port": int(os.getenv("SMTP_PORT", "587")),
        "email_address": os.getenv("EMAIL_ADDRESS", "").strip(),
        "email_password": os.getenv("EMAIL_PASSWORD", "").strip(),
        "email_to": os.getenv("EMAIL_TO", "").strip(),
    }
    if not cfg["email_to"]:
        cfg["email_to"] = cfg["email_address"]
    return cfg


# --------------------------------------------------------------------------- #
# Fetching news from Google News RSS
# --------------------------------------------------------------------------- #
def fetch_topic_news(topic: str, cfg: dict) -> list[Article]:
    """Fetch the top news items for a single topic via Google News RSS."""
    ceid = f"{cfg['country']}:{cfg['lang'].split('-')[0]}"
    url = (
        "https://news.google.com/rss/search?"
        f"q={quote_plus(topic)}"
        f"&hl={cfg['lang']}&gl={cfg['country']}&ceid={quote_plus(ceid)}"
    )

    feed = feedparser.parse(url)
    articles: list[Article] = []
    for entry in feed.entries[: cfg["per_topic"]]:
        # The RSS "source" tag holds the publisher name when present.
        source = ""
        if getattr(entry, "source", None) is not None:
            source = getattr(entry.source, "title", "") or ""
        articles.append(
            Article(
                topic=topic,
                title=getattr(entry, "title", "(no title)"),
                link=getattr(entry, "link", ""),
                source=source,
                published=getattr(entry, "published", ""),
            )
        )
    return articles


def matches_keywords(text: str, keywords: list[str]) -> bool:
    """True if `text` contains at least one keyword (whole-word, case-insensitive).

    Used to keep only articles that are actually relevant (e.g. mention AI).
    Returns True when no keywords are configured (filter disabled).
    """
    if not keywords:
        return True
    for kw in keywords:
        if re.search(rf"\b{re.escape(kw)}\b", text, re.IGNORECASE):
            return True
    return False


_TITLE_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "is",
    "are", "as", "at", "by", "from", "how", "why", "what", "new", "says", "amid",
    "into", "over", "after", "this", "that", "its", "it", "be", "will", "can",
}


def title_tokens(title: str) -> set[str]:
    """Normalize a headline into a set of significant word tokens for comparison."""
    # Google News appends ' - Publisher'; drop that trailing source segment.
    if " - " in title:
        title = title.rsplit(" - ", 1)[0]
    title = title.lower()
    title = re.sub(r"[^a-z0-9\uac00-\ud7a3\s]", " ", title)
    return {
        w for w in title.split()
        if len(w) > 1 and w not in _TITLE_STOPWORDS
    }


def is_duplicate(tokens: set[str], seen: list[set[str]], threshold: float) -> bool:
    """True if `tokens` overlaps an already-seen headline above the Jaccard threshold."""
    if not tokens:
        return False
    for prev in seen:
        union = tokens | prev
        if not union:
            continue
        jaccard = len(tokens & prev) / len(union)
        if jaccard >= threshold:
            return True
    return False


def resolve_real_url(google_url: str) -> str:
    """Google News links are encoded redirects. Decode to the real article URL."""
    try:
        from googlenewsdecoder import gnewsdecoder

        result = gnewsdecoder(google_url, interval=1)
        if result.get("status") and result.get("decoded_url"):
            return result["decoded_url"]
    except Exception:
        pass
    return google_url


def fetch_article_text(url: str, max_chars: int = 6000) -> str:
    """Best-effort extraction of an article's main text for summarization."""
    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception:
        return ""

    soup = BeautifulSoup(resp.text, "lxml")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()

    paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
    text = "\n".join(p for p in paragraphs if len(p) > 40)
    return text[:max_chars]


# --------------------------------------------------------------------------- #
# Summarization with Gemini
# --------------------------------------------------------------------------- #
def build_summarizer(cfg: dict):
    """Return a function that summarizes (title, text) -> summary string."""
    api_key = cfg["gemini_api_key"]
    if not api_key or api_key == "your_gemini_api_key_here":
        print("  [warn] No GEMINI_API_KEY set; falling back to raw snippets.")
        return None

    from google import genai

    client = genai.Client(api_key=api_key)
    model = cfg["gemini_model"]
    language = cfg["summary_language"]

    def summarize(title: str, text: str) -> tuple[str, str]:
        """Return (translated_title, summary), both written in `language`."""
        system_prompt = (
            "You are an expert Cyber Threat Intelligence (CTI) analyst working for Hunesion (휴네시온), "
            "a company specializing in Network Isolation / Cross-Domain Solutions (망연계 - i-oneNet), "
            "Systems Access Control (접근제어 - NGS), and Public/Financial sector infrastructure security.\n\n"
            "Your role is to strictly analyze raw threat data, filtering heavily for corporate relevance "
            "and eliminating outside knowledge or hallucinated details."
        )

        content = text if text else title
        prompt = (
            f"You are cybersecurity professional who are researching cybersecurity trends by readingnews article.\n"
            f"1) Translate the title into {language}.\n"
            f"2) Summarize the article in 3-5 concise, factual, neutral sentences in {language}.\n\n"
            "Respond in EXACTLY this format, nothing else:\n"
            "TITLE: <translated title>\n"
            "SUMMARY: <scale>\n<summary>\n\n"
            f"Article title: {title}\n\nArticle body:\n{content}"
        )
        last_exc = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = client.models.generate_content(model=model, contents=prompt)
                return _parse_summary(resp.text or "")
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if not _is_retryable(exc) or attempt == MAX_RETRIES - 1:
                    break
                wait = RETRY_BASE_DELAY * (2 ** attempt)
                print(f"    [retry {attempt + 1}/{MAX_RETRIES - 1}] {type(exc).__name__}; "
                      f"waiting {wait}s...")
                time.sleep(wait)
        return "", f"(Could not summarize: {last_exc})"

    return summarize


MAX_RETRIES = 4
RETRY_BASE_DELAY = 5  # seconds; doubles each retry (5, 10, 20)


def _is_retryable(exc: Exception) -> bool:
    """True for transient Gemini errors worth retrying (overload / rate limit)."""
    text = str(exc)
    return any(code in text for code in ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED"))


def _parse_summary(raw: str) -> tuple[str, str]:
    """Parse the 'TITLE: ... / SUMMARY: ...' response into (title, summary)."""
    title, summary = "", ""
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("TITLE:"):
            title = stripped[len("TITLE:"):].strip()
        elif stripped.upper().startswith("SUMMARY:"):
            summary = stripped[len("SUMMARY:"):].strip()
        elif summary:  # continuation lines of a multi-line summary
            summary += " " + stripped
    if not summary:  # model ignored the format; use the whole thing as summary
        summary = raw.strip()
    return title, summary


# --------------------------------------------------------------------------- #
# HTML report + email
# --------------------------------------------------------------------------- #
def build_html(grouped: dict[str, list[Article]]) -> str:
    now = datetime.now()
    weekday_ko = ["월", "화", "수", "목", "금", "토", "일"][now.weekday()]
    today = f"{now.year}년 {now.month}월 {now.day}일 ({weekday_ko})"
    parts = [
        "<html><body style=\"font-family:'Malgun Gothic',Arial,sans-serif;"
        "color:#222;max-width:720px;margin:auto;\">",
        f"<h1 style=\"color:#1a73e8;\">일일 뉴스 리포트</h1>",
        f"<p style=\"color:#666;\">{escape(today)}</p>",
    ]
    for topic, articles in grouped.items():
        parts.append(
            f"<h2 style=\"border-bottom:2px solid #1a73e8;padding-bottom:4px;\">"
            f"{escape(topic)}</h2>"
        )
        for i, a in enumerate(articles, 1):
            display_title = a.title_translated or a.title
            meta = " &middot; ".join(x for x in [escape(a.source), escape(a.published)] if x)
            # Show the original English headline only when we translated it.
            original = ""
            if a.title_translated:
                original = (
                    f"<div style=\"font-size:12px;color:#aaa;margin:1px 0;\">"
                    f"{escape(a.title)}</div>"
                )
            parts.append(
                f"<div style=\"margin:0 0 18px;\">"
                f"<a href=\"{escape(a.link)}\" style=\"font-size:16px;font-weight:bold;"
                f"color:#1a0dab;text-decoration:none;\">{i}. {escape(display_title)}</a>"
                f"{original}"
                f"<div style=\"font-size:12px;color:#888;margin:2px 0;\">{meta}</div>"
                f"<div style=\"font-size:14px;line-height:1.5;\">{escape(a.summary)}</div>"
                f"</div>"
            )
    parts.append("</body></html>")
    return "".join(parts)


def send_email(html: str, cfg: dict) -> None:
    if not cfg["email_address"] or not cfg["email_password"]:
        print("  [warn] Email credentials missing; skipping send.")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"일일 뉴스 리포트 - {today}"
    msg["From"] = cfg["email_address"]
    msg["To"] = cfg["email_to"]
    msg.attach(MIMEText(html, "html", "utf-8"))

    # local_hostname is forced to "localhost" because smtplib sends the machine
    # hostname in the EHLO command as ASCII; a non-ASCII (e.g. Korean) PC name
    # would otherwise raise UnicodeEncodeError.
    with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"], local_hostname="localhost") as server:
        server.starttls()
        server.login(cfg["email_address"], cfg["email_password"])
        server.sendmail(cfg["email_address"], [cfg["email_to"]], msg.as_string())
    print(f"  Email sent to {cfg['email_to']}")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:
    cfg = load_config()
    summarize = build_summarizer(cfg)

    keywords = cfg["require_keywords"]
    seen_titles: list[set[str]] = []  # de-dup across the whole run, not just per topic
    grouped: dict[str, list[Article]] = {}
    for label, query in cfg["topics"]:
        print(f"Fetching: {label}")
        articles = fetch_topic_news(query+'AND (site: "bleepingcomputer.com" OR site:"securityweek.com" OR site:"thehackernews.com" OR site:"krebsonsecurity.com" OR site:"therecord.media" OR site:"darkreading.com" OR site:"cisa.gov")', cfg)
        articles += fetch_topic_news('("데이터 유출" OR "랜섬웨어" OR "제로 데이" OR "취약점") AND ("기업" OR "회사" OR "사업") AND (site:boannews.com OR site:dailysecu.com)', {'country': 'KR', 'lang': 'kr-KR', 'per_topic': 10})
        print(articles)
        kept: list[Article] = []
        skipped_kw = skipped_dup = 0
        for a in articles:
            a.topic = label
            # De-dup first (cheap, title-based) so duplicate stories don't even
            # get fetched or summarized.
            tokens = title_tokens(a.title)
            if cfg["dedupe"] and is_duplicate(tokens, seen_titles, cfg["dedupe_threshold"]):
                skipped_dup += 1
                continue

            real_url = resolve_real_url(a.link)
            a.link = real_url
            text = fetch_article_text(real_url) if (summarize or keywords) else ""

            # Relevance filter: drop articles that don't mention the required
            # keywords in the title or body (e.g. cybersecurity news with no AI).
            if not matches_keywords(f"{a.title}\n{text}", keywords):
                skipped_kw += 1
                continue

            seen_titles.append(tokens)
            if summarize:
                a.title_translated, a.summary = summarize(a.title, text)
                time.sleep(1.0)  # be gentle on the LLM free-tier limits
            else:
                a.summary = "(요약 없음 - GEMINI_API_KEY를 설정하세요)"
            kept.append(a)
        grouped[label] = kept
        notes = []
        if cfg["dedupe"]:
            notes.append(f"{skipped_dup} duplicates")
        if keywords:
            notes.append(f"{skipped_kw} off-topic")
        suffix = f" ({', '.join(notes)} skipped)" if notes else ""
        print(f"  {len(kept)} articles processed.{suffix}")

    html = build_html(grouped)

    out_path = os.path.join(os.path.dirname(__file__), "latest_report.html")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"Saved local copy: {out_path}")

    send_email(html, cfg)
    print("Done.")


if __name__ == "__main__":
    main()
