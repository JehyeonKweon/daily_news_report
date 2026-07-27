"""Title-token deduplication."""

from __future__ import annotations

import re

from core.models import Article

_TITLE_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "is",
    "are", "as", "at", "by", "from", "how", "why", "what", "new", "says", "amid",
    "into", "over", "after", "this", "that", "its", "it", "be", "will", "can",
}


def title_tokens(title: str) -> set[str]:
    if " - " in title:
        title = title.rsplit(" - ", 1)[0]
    title = title.lower()
    title = re.sub(r"[^a-z0-9\uac00-\ud7a3\s]", " ", title)
    return {
        w for w in title.split()
        if len(w) > 1 and w not in _TITLE_STOPWORDS
    }


def is_duplicate(tokens: set[str], seen: list[set[str]], threshold: float) -> bool:
    if not tokens:
        return False
    for prev in seen:
        union = tokens | prev
        if not union:
            continue
        if len(tokens & prev) / len(union) >= threshold:
            return True
    return False


def select_unique_articles(
    pool: list[Article],
    target: int,
    seen_titles: list[set[str]],
    *,
    dedupe: bool,
    threshold: float,
    start: int = 0,
) -> tuple[list[Article], int, int]:
    """Walk `pool` from `start` until `target` unique titles.

    Returns (unique_articles, skipped_duplicates, next_index).
    """
    unique: list[Article] = []
    skipped_dup = 0
    i = start
    while i < len(pool) and len(unique) < target:
        article = pool[i]
        i += 1
        tokens = title_tokens(article.title)
        if dedupe and is_duplicate(tokens, seen_titles, threshold):
            skipped_dup += 1
            continue
        seen_titles.append(tokens)
        unique.append(article)
    return unique, skipped_dup, i
