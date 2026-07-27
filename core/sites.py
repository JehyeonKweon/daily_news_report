"""Whitelist of publisher RSS feeds for the web board."""

from __future__ import annotations

import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlparse

import feedparser
import requests

from core.config import CONFIG_DIR, ROOT_DIR
from core.models import Article
from core.rss import RSS_FETCH_CAP

SITES_PATH = os.path.join(CONFIG_DIR, "international_sites.txt")
STATUS_PATH = os.path.join(ROOT_DIR, "data", "board_sites_status.json")

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

_status_lock = threading.Lock()


def _request_headers_for(feed_url: str) -> dict[str, str]:
    headers = dict(REQUEST_HEADERS)
    host = urlparse(feed_url).scheme + "://" + (urlparse(feed_url).netloc or "")
    if host != "://":
        headers["Referer"] = host.rstrip("/") + "/"
    return headers


def _http_get(feed_url: str, *, timeout: int = 25):
    """GET feed bytes. Prefer curl_cffi (Chrome TLS) to pass CDN/bot checks."""
    try:
        from curl_cffi import requests as curl_requests

        # Do not override UA/Accept — impersonate supplies a matching browser fingerprint.
        for impersonate in ("chrome", "safari"):
            try:
                resp = curl_requests.get(
                    feed_url,
                    timeout=timeout,
                    impersonate=impersonate,
                )
                if resp.status_code < 400 and resp.content:
                    return resp
            except Exception:
                continue
    except ImportError:
        pass

    return requests.get(
        feed_url,
        headers=_request_headers_for(feed_url),
        timeout=timeout,
    )


@dataclass
class SiteEntry:
    domain: str
    feed_url: str


@dataclass
class SiteStatus:
    domain: str
    feed_url: str
    ok: bool = True
    error: str = ""
    last_checked: str = ""
    entry_count: int = 0


@dataclass
class SiteFetchResult:
    site: SiteEntry
    articles: list[Article] = field(default_factory=list)
    status: SiteStatus | None = None


def normalize_domain(raw: str) -> str:
    text = (raw or "").strip().lower()
    if not text:
        return ""
    if "://" in text:
        text = urlparse(text).netloc or text
    text = text.split("/")[0]
    if text.startswith("www."):
        text = text[4:]
    return text.strip(".")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_sites(path: str = SITES_PATH) -> list[SiteEntry]:
    if not os.path.isfile(path):
        return []
    sites: list[SiteEntry] = []
    seen: set[str] = set()
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "|" in stripped:
                domain_raw, feed_raw = stripped.split("|", 1)
            else:
                domain_raw, feed_raw = stripped, ""
            domain = normalize_domain(domain_raw)
            feed_url = feed_raw.strip()
            if not domain or not feed_url:
                continue
            if domain in seen:
                continue
            seen.add(domain)
            sites.append(SiteEntry(domain=domain, feed_url=feed_url))
    return sites


def save_sites(sites: list[SiteEntry], path: str = SITES_PATH) -> None:
    lines = [
        "# Web board whitelist: one site per line.",
        "# Format: domain | feed_url",
        "# Lines starting with # are comments.",
        "",
    ]
    for site in sites:
        lines.append(f"{site.domain} | {site.feed_url}")
    lines.append("")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    os.replace(tmp, path)


def load_site_statuses() -> dict[str, SiteStatus]:
    if not os.path.isfile(STATUS_PATH):
        return {}
    try:
        with open(STATUS_PATH, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, SiteStatus] = {}
    for key, item in raw.items():
        if not isinstance(item, dict):
            continue
        domain = normalize_domain(item.get("domain") or key)
        if not domain:
            continue
        out[domain] = SiteStatus(
            domain=domain,
            feed_url=item.get("feed_url", ""),
            ok=bool(item.get("ok", True)),
            error=str(item.get("error", "") or ""),
            last_checked=str(item.get("last_checked", "") or ""),
            entry_count=int(item.get("entry_count", 0) or 0),
        )
    return out


def save_site_statuses(statuses: dict[str, SiteStatus]) -> None:
    os.makedirs(os.path.dirname(STATUS_PATH), exist_ok=True)
    payload = {d: asdict(s) for d, s in statuses.items()}
    tmp = STATUS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, STATUS_PATH)


def update_site_status(status: SiteStatus) -> None:
    with _status_lock:
        known = {s.domain for s in load_sites()}
        statuses = {d: s for d, s in load_site_statuses().items() if d in known}
        if status.domain in known:
            statuses[status.domain] = status
        save_site_statuses(statuses)


def sync_statuses_with_whitelist() -> dict[str, SiteStatus]:
    with _status_lock:
        sites = load_sites()
        statuses = load_site_statuses()
        known = {s.domain for s in sites}
        statuses = {d: s for d, s in statuses.items() if d in known}
        for site in sites:
            if site.domain not in statuses:
                statuses[site.domain] = SiteStatus(
                    domain=site.domain,
                    feed_url=site.feed_url,
                    ok=True,
                    error="",
                    last_checked="",
                    entry_count=0,
                )
            else:
                statuses[site.domain].feed_url = site.feed_url
        save_site_statuses(statuses)
        return statuses


def add_site(domain: str, feed_url: str) -> SiteEntry:
    feed = (feed_url or "").strip()
    if not feed or not feed.startswith(("http://", "https://")):
        raise ValueError("A valid feed URL (http/https) is required")
    domain_n = normalize_domain(domain) or normalize_domain(feed)
    if not domain_n:
        raise ValueError("Could not determine domain from feed URL")
    sites = load_sites()
    if any(s.domain == domain_n for s in sites):
        raise ValueError(f"Site already exists: {domain_n}")
    entry = SiteEntry(domain=domain_n, feed_url=feed)
    sites.append(entry)
    save_sites(sites)
    sync_statuses_with_whitelist()
    return entry


def remove_site(domain: str) -> SiteEntry | None:
    domain_n = normalize_domain(domain)
    sites = load_sites()
    kept: list[SiteEntry] = []
    removed: SiteEntry | None = None
    for site in sites:
        if site.domain == domain_n:
            removed = site
        else:
            kept.append(site)
    if removed is None:
        return None
    save_sites(kept)
    with _status_lock:
        statuses = load_site_statuses()
        statuses.pop(domain_n, None)
        save_site_statuses(statuses)
    return removed


def parse_published(entry) -> tuple[str, datetime | None]:
    """Return (display string, aware UTC datetime or None)."""
    for key in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, key, None)
        if parsed:
            try:
                dt = datetime(*parsed[:6], tzinfo=timezone.utc)
                return dt.isoformat(), dt
            except (TypeError, ValueError):
                pass
    for key in ("published", "updated"):
        raw = (getattr(entry, key, None) or "").strip()
        if not raw:
            continue
        try:
            dt = parsedate_to_datetime(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return raw, dt.astimezone(timezone.utc)
        except (TypeError, ValueError, IndexError, OverflowError):
            try:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return raw, dt.astimezone(timezone.utc)
            except ValueError:
                return raw, None
    return "", None


def _entry_link(entry, feed_url: str) -> str:
    link = (getattr(entry, "link", None) or "").strip()
    if not link and getattr(entry, "links", None):
        for item in entry.links:
            href = (item.get("href") or "").strip()
            if href:
                link = href
                break
    if link and not link.startswith(("http://", "https://")):
        link = urljoin(feed_url, link)
    return link


def _strip_html(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def entry_snippet(entry, max_chars: int = 6000) -> str:
    chunks: list[str] = []
    content = getattr(entry, "content", None)
    if content and isinstance(content, list):
        for block in content:
            val = block.get("value") if isinstance(block, dict) else getattr(block, "value", "")
            if val:
                chunks.append(str(val))
    summary = getattr(entry, "summary", None) or ""
    if summary:
        chunks.append(str(summary))
    raw = "\n".join(chunks)
    return _strip_html(raw)[:max_chars]


def fetch_site_feed(site: SiteEntry, *, limit: int = RSS_FETCH_CAP) -> SiteFetchResult:
    """Fetch one publisher RSS/Atom feed. Never raises — errors go into status."""
    checked = _now_iso()
    try:
        resp = _http_get(site.feed_url, timeout=25)
        if resp.status_code >= 400:
            status = SiteStatus(
                domain=site.domain,
                feed_url=site.feed_url,
                ok=False,
                error=f"HTTP {resp.status_code}",
                last_checked=checked,
                entry_count=0,
            )
            print(f"  [sites] {site.domain}: {status.error} ({site.feed_url})")
            return SiteFetchResult(site=site, articles=[], status=status)

        content = resp.content
        # Cloudflare challenge HTML sometimes slips through with 200
        head = content[:200].lstrip().lower()
        if head.startswith(b"<!doctype html") or b"just a moment" in head:
            status = SiteStatus(
                domain=site.domain,
                feed_url=site.feed_url,
                ok=False,
                error="Blocked by site protection (Cloudflare)",
                last_checked=checked,
                entry_count=0,
            )
            print(f"  [sites] {site.domain}: {status.error}")
            return SiteFetchResult(site=site, articles=[], status=status)

        parsed = feedparser.parse(content)
        articles: list[Article] = []
        for entry in parsed.entries[:limit]:
            title = (getattr(entry, "title", None) or "").strip() or "(no title)"
            link = _entry_link(entry, site.feed_url)
            guid = (
                getattr(entry, "id", None) or getattr(entry, "guid", None) or ""
            ).strip()
            published_raw, _dt = parse_published(entry)
            articles.append(
                Article(
                    topic="해외 보안 뉴스",
                    title=title,
                    link=link,
                    source=site.domain,
                    published=published_raw,
                    guid=guid,
                    summary=entry_snippet(entry),
                )
            )

        if not articles:
            err = "Feed returned no entries"
            if getattr(parsed, "bozo", False) and getattr(parsed, "bozo_exception", None):
                err = f"{err} ({parsed.bozo_exception})"
            status = SiteStatus(
                domain=site.domain,
                feed_url=site.feed_url,
                ok=False,
                error=err,
                last_checked=checked,
                entry_count=0,
            )
            print(f"  [sites] {site.domain}: {status.error}")
            return SiteFetchResult(site=site, articles=[], status=status)

        status = SiteStatus(
            domain=site.domain,
            feed_url=site.feed_url,
            ok=True,
            error="",
            last_checked=checked,
            entry_count=len(articles),
        )
        print(f"  [sites] {site.domain}: {len(articles)} entries")
        return SiteFetchResult(site=site, articles=articles, status=status)
    except requests.RequestException as exc:
        status = SiteStatus(
            domain=site.domain,
            feed_url=site.feed_url,
            ok=False,
            error=f"Request failed: {exc}",
            last_checked=checked,
            entry_count=0,
        )
        print(f"  [sites] {site.domain}: {status.error}")
        return SiteFetchResult(site=site, articles=[], status=status)
    except Exception as exc:  # noqa: BLE001 — isolate per-site failures
        status = SiteStatus(
            domain=site.domain,
            feed_url=site.feed_url,
            ok=False,
            error=f"Parse error: {exc}",
            last_checked=checked,
            entry_count=0,
        )
        print(f"  [sites] {site.domain}: {status.error}")
        return SiteFetchResult(site=site, articles=[], status=status)


def fetch_all_site_feeds(
    sites: list[SiteEntry] | None = None,
    *,
    max_workers: int = 8,
) -> list[SiteFetchResult]:
    targets = sites if sites is not None else load_sites()
    if not targets:
        return []
    results: list[SiteFetchResult] = []
    with ThreadPoolExecutor(max_workers=min(max_workers, len(targets))) as pool:
        futures = {pool.submit(fetch_site_feed, site): site for site in targets}
        for fut in as_completed(futures):
            result = fut.result()
            if result.status is not None:
                update_site_status(result.status)
            results.append(result)
    # Stable order matching whitelist
    order = {s.domain: i for i, s in enumerate(targets)}
    results.sort(key=lambda r: order.get(r.site.domain, 999))
    return results


def article_published_dt(article: Article) -> datetime | None:
    raw = (article.published or "").strip()
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError, IndexError, OverflowError):
        pass
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def filter_recent(articles: list[Article], days: int) -> list[Article]:
    if days <= 0:
        return articles
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    kept: list[Article] = []
    for article in articles:
        dt = article_published_dt(article)
        if dt is None:
            # Keep undated items so a bad date parser does not wipe a feed
            kept.append(article)
            continue
        if dt >= cutoff:
            kept.append(article)
    return kept
