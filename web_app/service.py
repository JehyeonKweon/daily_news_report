"""Fetch whitelist publisher RSS feeds, merge history, summarize new only."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import asdict
from datetime import datetime, timezone
from urllib.parse import urlparse

from core.articles import fetch_article_text, resolve_real_url
from core.config import load_base_config, load_prompt_file
from core.dedupe import is_duplicate, title_tokens
from core.gemini import (
    MIN_GEMINI_INTERVAL_SECONDS,
    build_summarizer,
    format_error_for_log,
    pace_interval,
)
from core.sites import (
    add_site,
    article_published_dt,
    fetch_all_site_feeds,
    fetch_site_feed,
    filter_recent,
    load_sites,
    normalize_domain,
    remove_site,
    sync_statuses_with_whitelist,
    update_site_status,
)
from web_app.store import (
    article_id_from_guid_or_link,
    article_max_age_days,
    ensure_loaded,
    get_state,
    max_summaries_per_refresh,
    prune_old_articles,
    remove_articles_for_source,
    state_as_dict,
    update_article_link,
    update_article_summary,
    upsert_from_rss,
)

_FEED_SNIPPETS: dict[str, str] = {}

_score_lock = threading.Lock()
_score_job: dict = {
    "running": False,
    "total": 0,
    "completed": 0,
    "ok": 0,
    "failed": 0,
    "current_title": "",
    "error": "",
}


def get_score_status() -> dict:
    with _score_lock:
        return dict(_score_job)


def _set_score_job(**kwargs) -> None:
    with _score_lock:
        _score_job.update(kwargs)


def start_scoring_background(prefer_ids: list[str] | None = None) -> bool:
    """Start Gemini scoring in a daemon thread. Returns False if already running."""
    with _score_lock:
        if _score_job["running"]:
            return False
        _score_job.update(
            {
                "running": True,
                "total": 0,
                "completed": 0,
                "ok": 0,
                "failed": 0,
                "current_title": "",
                "error": "",
            }
        )

    def _worker() -> None:
        try:
            summarize_pending(prefer_ids=prefer_ids, track_job=True)
        except Exception as exc:  # noqa: BLE001
            print(f"  [board] background score error: {exc}")
            _set_score_job(error=str(exc))
        finally:
            _set_score_job(running=False, current_title="")

    threading.Thread(target=_worker, name="board-score", daemon=True).start()
    return True


def _board_gemini_config() -> dict:
    """Env config + web-board-only prompts (separate from email category prompts)."""
    cfg = load_base_config()
    prompt_dir = os.path.join(os.path.dirname(__file__), "prompts")
    cfg["category"] = "web_board"
    cfg["gemini_system_prompt"] = load_prompt_file(
        os.path.join(prompt_dir, "gemini_system_prompt.txt")
    )
    cfg["gemini_user_prompt"] = load_prompt_file(
        os.path.join(prompt_dir, "gemini_user_prompt.txt")
    )
    return cfg


def _is_google_news_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return "news.google." in host


def resolve_publisher_links(article_ids: list[str] | None = None) -> int:
    """Decode Google News redirect URLs to publisher URLs. Returns how many updated."""
    ensure_loaded()
    state = get_state()
    targets = (
        [state.by_id(i) for i in article_ids if state.by_id(i)]
        if article_ids is not None
        else state.sorted_list()
    )
    updated = 0
    for article in targets:
        if article is None or not article.link:
            continue
        if not _is_google_news_url(article.link):
            continue
        real = resolve_real_url(article.link)
        if real and real != article.link:
            update_article_link(article.id, real)
            updated += 1
    return updated


def _dedupe_articles(
    articles: list,
    *,
    threshold: float,
    existing_tokens: list[set[str]] | None = None,
    keep_ids: set[str] | None = None,
) -> tuple[list, int]:
    """Keep first unique titles; skip near-duplicates (Jaccard).

    ``existing_tokens`` seeds comparison with titles already on the board so a
    later outlet's take on the same story is skipped even if the earlier card
    is not in this RSS batch.

    ``keep_ids``: article ids already stored — always kept for upsert/refresh
    (they are not counted as skipped duplicates).
    """
    unique = []
    seen_tokens: list[set[str]] = list(existing_tokens or [])
    known_ids = keep_ids or set()
    skipped = 0
    for article in articles:
        aid = article_id_from_guid_or_link(article.guid, article.link, article.title)
        if aid in known_ids:
            unique.append(article)
            continue
        tokens = title_tokens(article.title)
        if is_duplicate(tokens, seen_tokens, threshold):
            skipped += 1
            continue
        seen_tokens.append(tokens)
        unique.append(article)
    return unique, skipped


def list_board_sites() -> dict:
    sites = load_sites()
    statuses = sync_statuses_with_whitelist()
    items = []
    for site in sites:
        st = statuses.get(site.domain)
        items.append(
            {
                "domain": site.domain,
                "feed_url": site.feed_url,
                "ok": True if st is None else st.ok,
                "error": "" if st is None else st.error,
                "last_checked": "" if st is None else st.last_checked,
                "entry_count": 0 if st is None else st.entry_count,
            }
        )
    return {"count": len(items), "sites": items}


def add_board_site(domain: str, feed_url: str, *, fetch_now: bool = True) -> dict:
    entry = add_site(domain, feed_url)
    fetched_new = 0
    status_payload = {
        "domain": entry.domain,
        "feed_url": entry.feed_url,
        "ok": True,
        "error": "",
        "last_checked": "",
        "entry_count": 0,
    }
    if fetch_now:
        result = fetch_site_feed(entry)
        if result.status is not None:
            update_site_status(result.status)
            status_payload = {
                "domain": result.status.domain,
                "feed_url": result.status.feed_url,
                "ok": result.status.ok,
                "error": result.status.error,
                "last_checked": result.status.last_checked,
                "entry_count": result.status.entry_count,
            }
        if result.articles:
            age_days = article_max_age_days()
            recent = filter_recent(result.articles, age_days)
            cfg = load_base_config()
            ensure_loaded()
            state = get_state()
            if cfg["dedupe"]:
                kept, _ = _dedupe_articles(
                    recent,
                    threshold=cfg["dedupe_threshold"],
                    existing_tokens=[
                        title_tokens(a.title) for a in state.articles.values()
                    ],
                    keep_ids=set(state.articles.keys()),
                )
            else:
                kept = recent
            items = []
            seen: set[str] = set()
            for a in kept:
                if not (a.link or a.title):
                    continue
                aid = article_id_from_guid_or_link(a.guid, a.link, a.title)
                if aid in seen:
                    continue
                seen.add(aid)
                items.append(
                    {
                        "id": aid,
                        "title": a.title,
                        "link": a.link,
                        "source": a.source or entry.domain,
                        "published": a.published,
                        "topic": a.topic or "해외 보안 뉴스",
                    }
                )
            new_ids, _ = upsert_from_rss(items=items)
            fetched_new = len(new_ids)
            if new_ids:
                start_scoring_background(prefer_ids=new_ids)

    articles = state_as_dict()
    articles["scoring"] = get_score_status()
    articles["sites"] = list_board_sites()["sites"]
    return {
        "site": status_payload,
        "new_count": fetched_new,
        "articles": articles,
    }


def remove_board_site(domain: str) -> dict:
    removed = remove_site(domain)
    if removed is None:
        raise KeyError(normalize_domain(domain) or domain)
    dropped = remove_articles_for_source(removed.domain)
    return {
        "removed": removed.domain,
        "articles_removed": dropped,
        "articles": state_as_dict(),
    }


def refresh_international_security(*, summarize_new: bool = True) -> dict:
    """Pull all whitelist RSS feeds, merge by guid, Gemini for unique unscored items."""
    global _FEED_SNIPPETS

    ensure_loaded()
    cfg = load_base_config()
    age_days = article_max_age_days()
    sites = load_sites()
    print(f"  [board] Fetching {len(sites)} site feed(s); max age {age_days}d")

    results = fetch_all_site_feeds(sites)
    feed_errors = sum(1 for r in results if r.status and not r.status.ok)

    pool = []
    for result in results:
        pool.extend(result.articles)

    recent = filter_recent(pool, age_days)
    recent.sort(
        key=lambda a: article_published_dt(a)
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    state = get_state()
    existing_ids = set(state.articles.keys())
    existing_tokens = [title_tokens(a.title) for a in state.articles.values()]

    if cfg["dedupe"]:
        unique, skipped_dup = _dedupe_articles(
            recent,
            threshold=cfg["dedupe_threshold"],
            existing_tokens=existing_tokens,
            keep_ids=existing_ids,
        )
    else:
        unique, skipped_dup = recent, 0

    items: list[dict] = []
    seen: set[str] = set()
    feed_snippets: dict[str, str] = {}
    for a in unique:
        if not (a.link or a.title):
            continue
        aid = article_id_from_guid_or_link(a.guid, a.link, a.title)
        if aid in seen:
            continue
        seen.add(aid)
        if a.summary:
            feed_snippets[aid] = a.summary
        items.append(
            {
                "id": aid,
                "title": a.title,
                "link": a.link,
                "source": a.source,
                "published": a.published,
                "topic": a.topic or "해외 보안 뉴스",
            }
        )

    new_ids, touched_ids = upsert_from_rss(items=items)
    pruned = prune_old_articles()
    decoded = resolve_publisher_links(touched_ids)
    _FEED_SNIPPETS = feed_snippets

    scoring_started = False
    if summarize_new:
        # Return after RSS; Gemini runs in background so the UI can update live.
        scoring_started = start_scoring_background(prefer_ids=new_ids)

    result = state_as_dict(
        new_count=len(new_ids),
        summarized_count=0,
        skipped_summary=0,
        skipped_duplicates=skipped_dup,
        feed_errors=feed_errors,
    )
    result["pruned_count"] = pruned
    result["decoded_urls"] = decoded
    result["sites"] = list_board_sites()["sites"]
    result["scoring"] = get_score_status()
    result["scoring_started"] = scoring_started
    return result


def summarize_pending(
    *,
    prefer_ids: list[str] | None = None,
    track_job: bool = False,
) -> tuple[int, int]:
    """Run Gemini on articles missing urgency/summary. Returns (ok_count, fail_or_deferred)."""
    ensure_loaded()
    state = get_state()
    prefer = set(prefer_ids or [])
    pending = [a for a in state.sorted_list() if a.needs_summary()]
    pending.sort(key=lambda a: (0 if a.id in prefer else 1, a.last_seen or ""))

    limit = max_summaries_per_refresh()
    if limit == 0:
        to_run = pending
        deferred = 0
    else:
        to_run = pending[:limit]
        deferred = len(pending) - len(to_run)

    if track_job:
        _set_score_job(total=len(to_run), completed=0, ok=0, failed=deferred)

    cfg = _board_gemini_config()
    summarize = build_summarizer(cfg, log=print)
    if summarize is None:
        if track_job:
            _set_score_job(
                failed=len(to_run) + deferred,
                error="GEMINI_API_KEY not configured",
            )
        return 0, len(to_run) + deferred

    ok = 0
    failed = deferred
    for article in to_run:
        if track_job:
            _set_score_job(current_title=article.title[:80])
        print(f"  [board] Summarizing: {article.title[:80]}")
        link = article.link
        if _is_google_news_url(link):
            real_url = resolve_real_url(link)
            if real_url != link:
                update_article_link(article.id, real_url)
                link = real_url
        else:
            real_url = link

        text = fetch_article_text(real_url)
        if not text:
            text = _FEED_SNIPPETS.get(article.id, "")
        started = time.monotonic()
        title_t, _relevance, urgency, urgency_reason, summary, category = summarize(
            article.title, text
        )
        elapsed = time.monotonic() - started
        if not urgency and not summary.startswith("(Could not summarize:"):
            urgency = "MEDIUM"
            if not urgency_reason:
                urgency_reason = "모델이 긴급도를 비워 두어 MEDIUM으로 보정함."
        if not category and not summary.startswith("(Could not summarize:"):
            category = "기타"
        update_article_summary(
            article.id,
            title_translated=title_t,
            category=category,
            urgency=urgency,
            urgency_reason=urgency_reason,
            summary=summary,
        )
        if (
            summary.startswith("(Could not summarize:")
            or summary == "(cancelled)"
            or not urgency
        ):
            print(f"    [error] {format_error_for_log(summary or 'missing urgency')}")
            failed += 1
        else:
            ok += 1
        if track_job:
            with _score_lock:
                _score_job["completed"] = int(_score_job.get("completed", 0)) + 1
                _score_job["ok"] = ok
                _score_job["failed"] = failed
        pace_interval(elapsed, MIN_GEMINI_INTERVAL_SECONDS, None)

    return ok, failed


def summarize_one(article_id: str) -> dict:
    """Force Gemini on a single article (on-demand)."""
    ensure_loaded()
    article = get_state().by_id(article_id)
    if article is None:
        raise KeyError(article_id)

    cfg = _board_gemini_config()
    summarize = build_summarizer(cfg, log=print)
    if summarize is None:
        raise RuntimeError("GEMINI_API_KEY not configured")

    link = article.link
    if _is_google_news_url(link):
        real_url = resolve_real_url(link)
        update_article_link(article_id, real_url)
    else:
        real_url = link

    text = fetch_article_text(real_url) or _FEED_SNIPPETS.get(article_id, "")
    started = time.monotonic()
    title_t, _relevance, urgency, urgency_reason, summary, category = summarize(
        article.title, text
    )
    elapsed = time.monotonic() - started
    pace_interval(elapsed, MIN_GEMINI_INTERVAL_SECONDS, None)

    if not urgency and not summary.startswith("(Could not summarize:"):
        urgency = "MEDIUM"
        if not urgency_reason:
            urgency_reason = "모델이 긴급도를 비워 두어 MEDIUM으로 보정함."
    if not category and not summary.startswith("(Could not summarize:"):
        category = "기타"

    updated = update_article_summary(
        article_id,
        title_translated=title_t,
        category=category,
        urgency=urgency,
        urgency_reason=urgency_reason,
        summary=summary,
    )
    if updated is None:
        raise KeyError(article_id)
    return asdict(updated)
