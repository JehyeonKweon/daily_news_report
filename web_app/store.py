"""JSON history store for the web triage board (guid-keyed, disk-backed)."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone

from core.config import ROOT_DIR

DATA_DIR = os.path.join(ROOT_DIR, "data")
HISTORY_PATH = os.path.join(DATA_DIR, "board_history.json")
DEFAULT_RETENTION_DAYS = 14

_lock = threading.Lock()


@dataclass
class BoardArticle:
    id: str  # Google News RSS guid (or link hash fallback)
    title: str
    link: str
    source: str
    published: str
    topic: str = "해외 보안 뉴스"
    title_translated: str = ""
    summary: str = ""
    relevance: str = ""  # email digest only; unused on web board
    category: str = ""  # see category_counts keys
    urgency: str = ""  # URGENT | HIGH | MEDIUM | LOW | ""
    urgency_reason: str = ""
    first_seen: str = ""
    last_seen: str = ""
    summarized_at: str = ""

    def needs_summary(self) -> bool:
        if not self.urgency:
            return True
        if not self.summary:
            return True
        if self.summary.startswith("(Could not summarize:"):
            return True
        if self.summary == "(cancelled)":
            return True
        return False


@dataclass
class BoardState:
    articles: dict[str, BoardArticle] = field(default_factory=dict)
    updated_at: str = ""
    rss_url: str = ""
    topic_url: str = ""

    def by_id(self, article_id: str) -> BoardArticle | None:
        return self.articles.get(article_id)

    def sorted_list(self) -> list[BoardArticle]:
        def sort_key(a: BoardArticle) -> tuple:
            return (a.last_seen or "", a.published or "", a.title)

        return sorted(self.articles.values(), key=sort_key, reverse=True)


_state = BoardState()


def article_id_from_guid_or_link(guid: str, link: str, title: str = "") -> str:
    raw = (guid or "").strip()
    if raw:
        return raw
    seed = (link or title or "").strip()
    if not seed:
        seed = "unknown"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def retention_days() -> int:
    raw = os.getenv("BOARD_RETENTION_DAYS", str(DEFAULT_RETENTION_DAYS)).strip()
    try:
        days = int(raw)
    except ValueError:
        return DEFAULT_RETENTION_DAYS
    return max(1, days)


def max_summaries_per_refresh() -> int:
    """Max Gemini calls per refresh. 0 = no cap (score every pending article)."""
    raw = os.getenv("BOARD_MAX_NEW_SUMMARIES", "0").strip()
    try:
        n = int(raw)
    except ValueError:
        return 0
    return max(0, n)


def article_max_age_days() -> int:
    """Only keep / ingest articles published within this many days (web board)."""
    raw = os.getenv("BOARD_ARTICLE_MAX_AGE_DAYS", "3").strip()
    try:
        days = int(raw)
    except ValueError:
        return 3
    return max(1, days)


def get_state() -> BoardState:
    return _state


def ensure_loaded() -> BoardState:
    with _lock:
        if not _state.articles and os.path.isfile(HISTORY_PATH):
            _load_unlocked()
        return _state


def _load_unlocked() -> None:
    global _state
    if not os.path.isfile(HISTORY_PATH):
        _state = BoardState()
        return
    try:
        with open(HISTORY_PATH, encoding="utf-8") as fh:
            text = fh.read().strip()
        if not text:
            _state = BoardState()
            return
        raw = json.loads(text)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        # Empty or corrupt history — start fresh rather than crash startup.
        _state = BoardState()
        return
    if not isinstance(raw, dict):
        _state = BoardState()
        return
    articles: dict[str, BoardArticle] = {}
    for key, item in (raw.get("articles") or {}).items():
        if not isinstance(item, dict):
            continue
        articles[key] = BoardArticle(
            id=item.get("id") or key,
            title=item.get("title", ""),
            link=item.get("link", ""),
            source=item.get("source", ""),
            published=item.get("published", ""),
            topic=item.get("topic", "해외 보안 뉴스"),
            title_translated=item.get("title_translated", ""),
            summary=item.get("summary", ""),
            relevance=item.get("relevance", ""),
            category=item.get("category", ""),
            urgency=item.get("urgency", ""),
            urgency_reason=item.get("urgency_reason", ""),
            first_seen=item.get("first_seen", ""),
            last_seen=item.get("last_seen", ""),
            summarized_at=item.get("summarized_at", ""),
        )
    _state = BoardState(
        articles=articles,
        updated_at=raw.get("updated_at", "") or "",
        rss_url=raw.get("rss_url", "") or "",
        topic_url=raw.get("topic_url", "") or "",
    )


def save_state() -> None:
    with _lock:
        _save_unlocked()


def _save_unlocked() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    payload = {
        "updated_at": _state.updated_at,
        "rss_url": _state.rss_url,
        "topic_url": _state.topic_url,
        "articles": {aid: asdict(article) for aid, article in _state.articles.items()},
    }
    tmp_path = HISTORY_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    os.replace(tmp_path, HISTORY_PATH)


def prune_old_articles(days: int | None = None) -> int:
    """Remove articles whose last_seen is older than retention. Returns removed count."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days or retention_days())
    removed = 0
    with _lock:
        drop: list[str] = []
        for aid, article in _state.articles.items():
            seen = _parse_iso(article.last_seen) or _parse_iso(article.first_seen)
            if seen is None or seen < cutoff:
                drop.append(aid)
        for aid in drop:
            del _state.articles[aid]
            removed += 1
        if removed:
            _save_unlocked()
    return removed


def urgency_counts(articles: list[BoardArticle]) -> dict[str, int]:
    counts = {"URGENT": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for a in articles:
        key = (a.urgency or "").upper()
        if key in counts:
            counts[key] += 1
    return counts


def category_counts(articles: list[BoardArticle]) -> dict[str, int]:
    counts = {
        "취약점": 0,
        "랜섬웨어": 0,
        "공급망": 0,
        "국가배후": 0,
        "AI 보안": 0,
        "데이터유출": 0,
        "악성코드": 0,
        "피싱": 0,
        "클라우드": 0,
        "정책·규제": 0,
        "기타": 0,
    }
    for a in articles:
        key = (a.category or "").strip()
        if key in counts:
            counts[key] += 1
    return counts


def state_as_dict(
    *,
    new_count: int = 0,
    summarized_count: int = 0,
    skipped_summary: int = 0,
    skipped_duplicates: int = 0,
    feed_errors: int = 0,
) -> dict:
    ensure_loaded()
    articles = _state.sorted_list()
    return {
        "updated_at": _state.updated_at,
        "rss_url": _state.rss_url,
        "topic_url": "",
        "count": len(articles),
        "new_count": new_count,
        "summarized_count": summarized_count,
        "skipped_summary": skipped_summary,
        "skipped_duplicates": skipped_duplicates,
        "feed_errors": feed_errors,
        "retention_days": retention_days(),
        "article_max_age_days": article_max_age_days(),
        "urgency_counts": urgency_counts(articles),
        "category_counts": category_counts(articles),
        "articles": [asdict(a) for a in articles],
    }


def upsert_from_rss(
    *,
    rss_url: str = "",
    topic_url: str = "",
    items: list[dict],
) -> tuple[list[str], list[str]]:
    """Merge RSS items into history.

    items: dicts with keys id, title, link, source, published, topic
    Returns (new_ids, touched_ids).
    """
    now = _now_iso()
    new_ids: list[str] = []
    touched_ids: list[str] = []
    with _lock:
        if not _state.articles and os.path.isfile(HISTORY_PATH):
            _load_unlocked()
        for item in items:
            aid = item["id"]
            existing = _state.articles.get(aid)
            if existing is None:
                article = BoardArticle(
                    id=aid,
                    title=item["title"],
                    link=item["link"],
                    source=item["source"],
                    published=item["published"],
                    topic=item.get("topic") or "해외 보안 뉴스",
                    first_seen=now,
                    last_seen=now,
                )
                _state.articles[aid] = article
                new_ids.append(aid)
            else:
                existing.title = item["title"] or existing.title
                existing.link = item["link"] or existing.link
                existing.source = item["source"] or existing.source
                existing.published = item["published"] or existing.published
                if item.get("topic"):
                    existing.topic = item["topic"]
                existing.last_seen = now
            touched_ids.append(aid)
        if rss_url:
            _state.rss_url = rss_url
        _state.topic_url = topic_url or ""
        _state.updated_at = now
        _save_unlocked()
    return new_ids, touched_ids


def remove_articles_for_source(domain: str) -> int:
    """Delete articles whose source matches domain (www. stripped). Returns count."""
    from core.sites import normalize_domain

    target = normalize_domain(domain)
    if not target:
        return 0
    removed = 0
    with _lock:
        if not _state.articles and os.path.isfile(HISTORY_PATH):
            _load_unlocked()
        drop = [
            aid
            for aid, article in _state.articles.items()
            if normalize_domain(article.source) == target
        ]
        for aid in drop:
            del _state.articles[aid]
            removed += 1
        if removed:
            _state.updated_at = _now_iso()
            _save_unlocked()
    return removed


def clear_all_articles() -> None:
    with _lock:
        _state.articles = {}
        _state.updated_at = _now_iso()
        _state.rss_url = ""
        _state.topic_url = ""
        _save_unlocked()


def update_article_link(article_id: str, link: str) -> BoardArticle | None:
    with _lock:
        article = _state.articles.get(article_id)
        if article is None:
            return None
        article.link = link
        _state.updated_at = _now_iso()
        _save_unlocked()
        return article


def update_article_summary(
    article_id: str,
    *,
    title_translated: str,
    urgency: str,
    urgency_reason: str,
    summary: str,
    category: str = "",
    relevance: str = "",
) -> BoardArticle | None:
    with _lock:
        article = _state.articles.get(article_id)
        if article is None:
            return None
        article.title_translated = title_translated
        article.relevance = relevance
        article.category = category
        article.urgency = urgency
        article.urgency_reason = urgency_reason
        article.summary = summary
        if (
            urgency
            and summary
            and not summary.startswith("(Could not summarize:")
            and summary != "(cancelled)"
        ):
            article.summarized_at = _now_iso()
        _state.updated_at = _now_iso()
        _save_unlocked()
        return article
