"""Fetch → summarize → HTML → email pipeline."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from threading import Event

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.articles import fetch_article_text, resolve_real_url
from core.config import ROOT_DIR, list_categories, load_run_config
from core.dedupe import is_duplicate, select_unique_articles, title_tokens
from core.gemini import (
    MIN_GEMINI_INTERVAL_SECONDS,
    build_summarizer,
    format_error_for_log,
    pace_interval,
    should_stop,
)
from core.models import Article, LogFn, RunOptions
from core.rss import (
    RSS_FETCH_CAP,
    build_search_query,
    feed_rss_url,
    fetch_feed_pool,
)
from email_app.html_report import build_html
from email_app.send import send_email


def run_report(options: RunOptions, log: LogFn = print, cancel_event: Event | None = None) -> str:
    """Fetch, summarize, save HTML, and email. Returns path to saved HTML."""
    cfg = load_run_config(options)
    summarize = build_summarizer(cfg, log=log, cancel_event=cancel_event)

    log(f"Category: {options.category}")
    log(f"Articles per feed: {options.article_count}")
    log(
        f"Last {options.days_back} day(s) "
        f"(when:{options.days_back}d on search feeds; no site filter)"
    )

    seen_titles: list[set[str]] = []
    grouped: dict[str, list[Article]] = {}

    for feed in cfg["feeds"]:
        label = feed["label"]
        n = options.article_count
        log(f"Fetching: {label}")
        rss_url = feed_rss_url(feed)
        if feed.get("mode") == "topic":
            log(f"  mode: topic ({feed['topic_id']})")
            log(f"  rss url: {rss_url}")
        else:
            days_back = feed.get("days_back", 1)
            query = build_search_query(feed["query"], days_back)
            log("  mode: search")
            log(f"  query: {query}")
            log(f"  rss url: {rss_url}")

        pool = fetch_feed_pool(feed)
        log(f"  RSS pool: {len(pool)} items (cap {RSS_FETCH_CAP})")
        if not pool:
            log(f"  [warn] No articles left for {label}.")
            grouped[label] = []
            continue

        # Phase 1a: dedupe first N RSS items
        unique: list[Article] = []
        skipped_dup = 0
        for a in pool[:n]:
            tokens = title_tokens(a.title)
            if cfg["dedupe"] and is_duplicate(tokens, seen_titles, cfg["dedupe_threshold"]):
                skipped_dup += 1
                continue
            seen_titles.append(tokens)
            unique.append(a)
        log(f"  After dedupe of first {n}: {len(unique)} unique ({skipped_dup} duplicates)")

        # Phase 1b: if short, fill from item N+1 onward until N unique
        cursor = n
        if len(unique) < n and cursor < len(pool):
            need = n - len(unique)
            log(f"  Filling {need} more from item {n + 1} onward...")
            extra, extra_dup, cursor = select_unique_articles(
                pool,
                need,
                seen_titles,
                dedupe=cfg["dedupe"],
                threshold=cfg["dedupe_threshold"],
                start=cursor,
            )
            unique.extend(extra)
            skipped_dup += extra_dup
            log(f"  Unique candidates: {len(unique)}/{n}")

        if not unique:
            log(f"  [warn] No unique articles for {label}.")
            grouped[label] = []
            continue

        # Phase 2: Gemini on unique list; if Gemini fails, pull more unique from pool
        kept: list[Article] = []
        skipped_err = 0
        queue = list(unique)
        qi = 0

        while len(kept) < n:
            if should_stop(cancel_event):
                log("Cancelled.")
                return ""

            if qi >= len(queue):
                if cursor >= len(pool):
                    break
                need = n - len(kept)
                log(f"  Need {need} more after Gemini skips; scanning from item {cursor + 1}...")
                extra, extra_dup, cursor = select_unique_articles(
                    pool,
                    need,
                    seen_titles,
                    dedupe=cfg["dedupe"],
                    threshold=cfg["dedupe_threshold"],
                    start=cursor,
                )
                skipped_dup += extra_dup
                if not extra:
                    break
                queue.extend(extra)
                continue

            a = queue[qi]
            qi += 1
            log(f"  Summarizing {len(kept) + 1}/{n} (candidate {qi})")

            real_url = resolve_real_url(a.link)
            a.link = real_url
            text = fetch_article_text(real_url) if summarize else ""

            if summarize:
                started = time.monotonic()
                a.title_translated, a.relevance, a.urgency, _reason, a.summary, _category = (
                    summarize(a.title, text)
                )
                elapsed = time.monotonic() - started
                if a.summary.startswith("(Could not summarize:") or a.summary == "(cancelled)":
                    skipped_err += 1
                    log(f"    [error] Skipped: {format_error_for_log(a.summary)}")
                    pace_interval(elapsed, MIN_GEMINI_INTERVAL_SECONDS, cancel_event)
                    continue
                kept.append(a)
                pace_interval(elapsed, MIN_GEMINI_INTERVAL_SECONDS, cancel_event)
            else:
                a.summary = "(요약 없음 - GEMINI_API_KEY를 설정하세요)"
                kept.append(a)

        grouped[label] = kept
        notes: list[str] = []
        if cfg["dedupe"] and skipped_dup:
            notes.append(f"{skipped_dup} duplicates skipped")
        if skipped_err:
            notes.append(f"{skipped_err} summarization errors skipped")
        if len(kept) < n:
            notes.append(f"short of target ({len(kept)}/{n})")
        suffix = f" ({', '.join(notes)})" if notes else ""
        log(f"  {len(kept)} articles processed.{suffix}")

    html = build_html(grouped, options.category)
    out_path = os.path.join(ROOT_DIR, "latest_report.html")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    log(f"Saved local copy: {out_path}")

    total_kept = sum(len(v) for v in grouped.values())
    if total_kept == 0:
        log("[warn] No articles in report; skipping email.")
        return out_path

    send_email(html, cfg, log=log)
    log("Done.")
    return out_path


def main() -> None:
    categories = list_categories()
    if not categories:
        sys.exit("No categories found. Add a folder under config/ (see config/보안/).")
    options = RunOptions(
        category=categories[0],
        article_count=10,
        international=True,
        korean=True,
    )
    run_report(options)


if __name__ == "__main__":
    main()
