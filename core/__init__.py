"""Shared library: models, config, RSS, dedupe, Gemini, article fetch."""

from core.models import Article, RunOptions, LogFn
from core.config import (
    CONFIG_DIR,
    ROOT_DIR,
    default_email_recipients,
    list_categories,
    load_run_config,
    parse_email_list,
)
from core.rss import (
    RSS_FETCH_CAP,
    SECURITY_INTL_TOPIC_ID,
    build_search_query,
    build_rss_search_url,
    build_rss_topic_url,
    feed_rss_url,
    fetch_feed_pool,
    fetch_feed_news,
    fetch_rss_entries,
)
from core.dedupe import is_duplicate, select_unique_articles, title_tokens
from core.articles import fetch_article_text, resolve_real_url
from core.gemini import (
    MIN_GEMINI_INTERVAL_SECONDS,
    build_summarizer,
    format_error_for_log,
    pace_interval,
    should_stop,
)

__all__ = [
    "Article",
    "RunOptions",
    "LogFn",
    "CONFIG_DIR",
    "ROOT_DIR",
    "RSS_FETCH_CAP",
    "SECURITY_INTL_TOPIC_ID",
    "MIN_GEMINI_INTERVAL_SECONDS",
    "default_email_recipients",
    "list_categories",
    "load_run_config",
    "parse_email_list",
    "build_search_query",
    "build_rss_search_url",
    "build_rss_topic_url",
    "feed_rss_url",
    "fetch_feed_pool",
    "fetch_feed_news",
    "fetch_rss_entries",
    "is_duplicate",
    "select_unique_articles",
    "title_tokens",
    "fetch_article_text",
    "resolve_real_url",
    "build_summarizer",
    "format_error_for_log",
    "pace_interval",
    "should_stop",
]
