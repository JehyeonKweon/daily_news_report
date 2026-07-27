"""Quick test: list categories and fetch a few articles (no Gemini/email).

Run: python test_script.py
"""

import sys

from core import (
    RSS_FETCH_CAP,
    RunOptions,
    build_search_query,
    feed_rss_url,
    fetch_feed_pool,
    is_duplicate,
    list_categories,
    load_run_config,
    select_unique_articles,
    title_tokens,
)


def main() -> None:
    categories = list_categories()
    if not categories:
        sys.exit("No categories found under config/")

    print(f"Categories: {', '.join(categories)}\n")
    n = 3

    for category in categories:
        print(f"===== Testing category: {category} =====\n")
        cfg = load_run_config(
            RunOptions(
                category=category,
                article_count=n,
                international=True,
                korean=True,
                days_back=1,
            )
        )

        seen: list[set[str]] = []
        for feed in cfg["feeds"]:
            print(f"=== {feed['label']} ===")
            print(f"mode: {feed.get('mode', 'search')}")
            if feed.get("mode") == "topic":
                print(f"topic_id: {feed['topic_id']}")
            else:
                query = build_search_query(feed["query"], feed.get("days_back", 1))
                print(f"query: {query}")
            print(f"rss url: {feed_rss_url(feed)}")

            pool = fetch_feed_pool(feed)
            print(f"RSS pool: {len(pool)} (cap {RSS_FETCH_CAP})")

            unique: list = []
            skipped = 0
            for a in pool[:n]:
                tokens = title_tokens(a.title)
                if is_duplicate(tokens, seen, cfg["dedupe_threshold"]):
                    skipped += 1
                    continue
                seen.append(tokens)
                unique.append(a)
            print(f"After dedupe of first {n}: {len(unique)} unique ({skipped} dups)")

            if len(unique) < n and len(pool) > n:
                need = n - len(unique)
                print(f"Filling {need} from item {n + 1}...")
                extra, extra_dup, _ = select_unique_articles(
                    pool,
                    need,
                    seen,
                    dedupe=True,
                    threshold=cfg["dedupe_threshold"],
                    start=n,
                )
                unique.extend(extra)
                skipped += extra_dup
                print(f"Unique candidates: {len(unique)}/{n} (total dups {skipped})")

            for i, article in enumerate(unique, 1):
                print(f"{i}. {article.title}")
                print(f"   source: {article.source}")
            print(f"Ready for Gemini: {len(unique)} articles.\n")


if __name__ == "__main__":
    main()
