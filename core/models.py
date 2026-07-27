"""Shared data types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

LogFn = Callable[[str], None]


@dataclass
class RunOptions:
    category: str
    article_count: int
    international: bool
    korean: bool
    email_to: str = ""
    days_back: int = 1


@dataclass
class Article:
    topic: str
    title: str
    link: str
    source: str
    published: str
    summary: str = ""
    title_translated: str = ""
    relevance: str = ""
    urgency: str = ""  # URGENT | HIGH | MEDIUM | LOW
    guid: str = ""  # Google News RSS <guid> (cluster id)
