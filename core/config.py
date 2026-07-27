"""Load .env and category config files."""

from __future__ import annotations

import os

from dotenv import load_dotenv

from core.models import RunOptions
from core.rss import SECURITY_INTL_TOPIC_ID

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(ROOT_DIR, "config")


def read_text_file(path: str) -> str:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Missing config file: {path}")
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def load_query_file(path: str) -> tuple[str, str]:
    """Read a search query file. Optional line: label: Report heading."""
    label = ""
    query_parts: list[str] = []
    for line in read_text_file(path).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.lower().startswith("label:"):
            label = stripped.split(":", 1)[1].strip()
            continue
        query_parts.append(stripped)
    if not query_parts:
        raise ValueError(f"No search query in {path}")
    if not label:
        label = os.path.splitext(os.path.basename(path))[0].replace("_", " ")
    return label, " ".join(query_parts)


def load_prompt_file(path: str) -> str:
    text = read_text_file(path).strip()
    if not text:
        raise ValueError(f"Empty prompt file: {path}")
    return text


def list_categories() -> list[str]:
    """Return category folder names under config/."""
    if not os.path.isdir(CONFIG_DIR):
        return []
    categories: list[str] = []
    for name in sorted(os.listdir(CONFIG_DIR)):
        path = os.path.join(CONFIG_DIR, name)
        prompt = os.path.join(path, "gemini_system_prompt.txt")
        if os.path.isdir(path) and os.path.isfile(prompt):
            categories.append(name)
    return categories


def category_dir(category: str) -> str:
    return os.path.join(CONFIG_DIR, category)


def parse_email_list(raw: str) -> list[str]:
    return [email.strip() for email in raw.split(",") if email.strip()]


def default_email_recipients() -> str:
    load_dotenv()
    return os.getenv("EMAIL_TO", "").strip() or os.getenv("EMAIL_ADDRESS", "").strip()


def load_base_config() -> dict:
    load_dotenv()
    cfg = {
        "gemini_api_key": os.getenv("GEMINI_API_KEY", "").strip(),
        "gemini_model": os.getenv("GEMINI_MODEL", "gemini-flash-latest").strip(),
        "summary_language": os.getenv("SUMMARY_LANGUAGE", "Korean").strip(),
        "dedupe": os.getenv("DEDUPE", "true").strip().lower() in ("1", "true", "yes", "on"),
        "dedupe_threshold": float(os.getenv("DEDUPE_THRESHOLD", "0.5")),
        "smtp_host": os.getenv("SMTP_HOST", "smtp.office365.com"),
        "smtp_port": int(os.getenv("SMTP_PORT", "587")),
        "email_address": os.getenv("EMAIL_ADDRESS", "").strip(),
        "email_password": os.getenv("EMAIL_PASSWORD", "").strip(),
        "email_to": os.getenv("EMAIL_TO", "").strip(),
        "news_lang": os.getenv("NEWS_LANG", "en-US"),
        "news_country": os.getenv("NEWS_COUNTRY", "US"),
        "news_lang_kr": os.getenv("NEWS_LANG_KR", "ko-KR"),
        "news_country_kr": os.getenv("NEWS_COUNTRY_KR", "KR"),
    }
    if not cfg["email_to"]:
        cfg["email_to"] = cfg["email_address"]
    return cfg


def load_run_config(options: RunOptions) -> dict:
    if options.category not in list_categories():
        raise ValueError(f"Unknown category: {options.category}")
    if not options.international and not options.korean:
        raise ValueError("Select at least one search: International or Korean.")
    if options.article_count < 1:
        raise ValueError("Article count must be at least 1.")
    if options.days_back < 1:
        raise ValueError("Days back must be at least 1.")

    cfg = load_base_config()
    cat_path = category_dir(options.category)
    cfg["category"] = options.category
    cfg["article_count"] = options.article_count
    cfg["gemini_system_prompt"] = load_prompt_file(
        os.path.join(cat_path, "gemini_system_prompt.txt")
    )
    cfg["gemini_user_prompt"] = load_prompt_file(
        os.path.join(cat_path, "gemini_user_prompt.txt")
    )

    feeds: list[dict] = []

    if options.international:
        label, query = load_query_file(os.path.join(cat_path, "international_query.txt"))
        if options.category == "보안":
            feeds.append(
                {
                    "label": label,
                    "mode": "topic",
                    "topic_id": SECURITY_INTL_TOPIC_ID,
                    "query": "",
                    "lang": cfg["news_lang"],
                    "country": cfg["news_country"],
                    "days_back": options.days_back,
                }
            )
        else:
            feeds.append(
                {
                    "label": label,
                    "mode": "search",
                    "query": query,
                    "lang": cfg["news_lang"],
                    "country": cfg["news_country"],
                    "days_back": options.days_back,
                }
            )
    if options.korean:
        label, query = load_query_file(os.path.join(cat_path, "korean_query.txt"))
        feeds.append(
            {
                "label": label,
                "mode": "search",
                "query": query,
                "lang": cfg["news_lang_kr"],
                "country": cfg["news_country_kr"],
                "days_back": options.days_back,
            }
        )

    cfg["feeds"] = feeds
    recipients = parse_email_list(options.email_to)
    if recipients:
        cfg["email_to"] = ", ".join(recipients)
    return cfg
