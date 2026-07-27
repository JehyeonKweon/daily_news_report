"""Build static HTML for the email digest."""

from __future__ import annotations

from datetime import datetime
from html import escape

from core.models import Article


def build_html(grouped: dict[str, list[Article]], category: str) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    parts = [
        "<html><body style=\"font-family:'Malgun Gothic',Arial,sans-serif;"
        "color:#222;max-width:720px;margin:auto;\">",
        "<h1 style=\"color:#1a73e8;margin-bottom:8px;\">일일 뉴스 리포트</h1>",
        f"<p style=\"font-size:18px;color:#333;margin:0 0 4px;\">{escape(category)}</p>",
        f"<p style=\"color:#666;margin:0 0 24px;\">{escape(today)}</p>",
    ]
    for topic, articles in grouped.items():
        parts.append(
            f"<h2 style=\"border-bottom:2px solid #1a73e8;padding-bottom:4px;\">"
            f"{escape(topic)}</h2>"
        )
        for i, a in enumerate(articles, 1):
            display_title = a.title_translated or a.title
            meta = " &middot; ".join(x for x in [escape(a.source), escape(a.published)] if x)
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
                + (
                    f"<div style=\"font-size:13px;font-weight:bold;color:#555;margin:6px 0 4px;\">"
                    f"{escape(a.relevance)}</div>"
                    if a.relevance else ""
                )
                + f"<div style=\"font-size:14px;line-height:1.5;\">{escape(a.summary)}</div>"
                f"</div>"
            )
    parts.append("</body></html>")
    return "".join(parts)
