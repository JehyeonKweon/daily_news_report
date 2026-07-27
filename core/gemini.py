"""Gemini summarization helpers."""

from __future__ import annotations

import re
import time
from threading import Event

from core.models import LogFn

MAX_RETRIES = 4
RETRY_BASE_DELAY = 10
MIN_GEMINI_INTERVAL_SECONDS = 20  # min seconds per Gemini call (RPM buffer for free tier)

_URGENCY_VALUES = ("URGENT", "HIGH", "MEDIUM", "LOW")

# Web board content categories (email digest ignores these).
_CATEGORY_VALUES = (
    "취약점",
    "랜섬웨어",
    "공급망",
    "국가배후",
    "AI 보안",
    "데이터유출",
    "악성코드",
    "피싱",
    "클라우드",
    "정책·규제",
    "기타",
)
_CATEGORY_ALIASES = {
    "vulnerability": "취약점",
    "vulnerabilities": "취약점",
    "vuln": "취약점",
    "cve": "취약점",
    "ransomware": "랜섬웨어",
    "ransom": "랜섬웨어",
    "supplychain": "공급망",
    "supply-chain": "공급망",
    "supply_chain": "공급망",
    "nationstate": "국가배후",
    "nation-state": "국가배후",
    "apt": "국가배후",
    "aisecurity": "AI 보안",
    "ai-security": "AI 보안",
    "ai": "AI 보안",
    "databreach": "데이터유출",
    "data-breach": "데이터유출",
    "data_breach": "데이터유출",
    "leak": "데이터유출",
    "malware": "악성코드",
    "trojan": "악성코드",
    "botnet": "악성코드",
    "phishing": "피싱",
    "socialengineering": "피싱",
    "cloud": "클라우드",
    "saas": "클라우드",
    "policy": "정책·규제",
    "regulation": "정책·규제",
    "compliance": "정책·규제",
    "other": "기타",
    "misc": "기타",
}


def should_stop(cancel_event: Event | None) -> bool:
    return bool(cancel_event and cancel_event.is_set())


def sleep_cancellable(seconds: float, cancel_event: Event | None) -> None:
    """Sleep in short chunks so Cancel can stop quickly."""
    end = time.time() + max(0.0, seconds)
    while time.time() < end:
        if should_stop(cancel_event):
            return
        time.sleep(min(0.25, end - time.time()))


def pace_interval(elapsed: float, target: float, cancel_event: Event | None) -> None:
    """Wait so each Gemini call takes at least `target` seconds end-to-end."""
    sleep_cancellable(max(0.0, target - elapsed), cancel_event)


def format_error_for_log(message: str, max_len: int = 180) -> str:
    """Shorten Gemini/API errors for the GUI log."""
    if message == "(cancelled)":
        return "cancelled"
    prefix = "(Could not summarize: "
    if message.startswith(prefix) and message.endswith(")"):
        message = message[len(prefix):-1].strip()
    if len(message) > max_len:
        return message[:max_len] + "..."
    return message


def normalize_urgency(raw: str) -> str:
    text = (raw or "").strip().upper()
    for value in _URGENCY_VALUES:
        if value in text:
            return value
    return ""


def normalize_category(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    for value in _CATEGORY_VALUES:
        if value == text or value.lower() == text.lower():
            return value
    key = re.sub(r"\s+", "", text.lower())
    if key in _CATEGORY_ALIASES:
        return _CATEGORY_ALIASES[key]
    for value in _CATEGORY_VALUES:
        if value in text:
            return value
    return ""


def build_summarizer(cfg: dict, log: LogFn = print, cancel_event: Event | None = None):
    api_key = cfg["gemini_api_key"]
    if not api_key or api_key == "your_gemini_api_key_here":
        log("  [warn] No GEMINI_API_KEY set; falling back to raw snippets.")
        return None

    from google import genai

    client = genai.Client(api_key=api_key)
    model = cfg["gemini_model"]
    language = cfg["summary_language"]
    system_template = cfg["gemini_system_prompt"]
    user_template = cfg["gemini_user_prompt"]

    def summarize(title: str, text: str) -> tuple[str, str, str, str, str, str]:
        """Return (title_translated, relevance, urgency, urgency_reason, summary, category)."""
        content = text if text else title
        system_prompt = system_template.format(language=language)
        prompt = user_template.format(language=language, title=title, content=content)
        last_exc = None
        for attempt in range(MAX_RETRIES):
            if should_stop(cancel_event):
                return "", "", "", "", "(cancelled)", ""
            try:
                resp = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=genai.types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        temperature=0.0,
                    ),
                )
                return parse_summary(resp.text or "")
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                # Quota errors are not worth retrying; they just waste requests/time.
                exc_text = str(exc)
                is_daily_quota = "GenerateRequestsPerDayPerProjectPerModel-FreeTier" in exc_text
                if is_daily_quota or (not _is_retryable(exc)) or attempt == MAX_RETRIES - 1:
                    break
                wait = RETRY_BASE_DELAY * (2 ** attempt)
                log(
                    f"    [retry {attempt + 1}/{MAX_RETRIES - 1}] {type(exc).__name__}; "
                    f"waiting {wait}s..."
                )
                sleep_cancellable(wait, cancel_event)
        return "", "", "", "", f"(Could not summarize: {last_exc})", ""

    return summarize


def _is_retryable(exc: Exception) -> bool:
    text = str(exc)
    return any(code in text for code in ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED"))


def parse_summary(raw: str) -> tuple[str, str, str, str, str, str]:
    """Parse Gemini output → (title, relevance, urgency, urgency_reason, summary, category)."""
    title, relevance, urgency, urgency_reason, summary, category = "", "", "", "", "", ""
    for line in raw.splitlines():
        stripped = line.strip()
        upper = stripped.upper()
        if upper.startswith("TITLE:"):
            title = stripped[len("TITLE:"):].strip()
        elif upper.startswith("RELEVANCE:"):
            relevance = stripped[len("RELEVANCE:"):].strip()
        elif upper.startswith("CATEGORY:"):
            category = normalize_category(stripped[len("CATEGORY:"):])
        elif upper.startswith("URGENCY_REASON:"):
            urgency_reason = stripped[len("URGENCY_REASON:"):].strip()
        elif upper.startswith("URGENCY:"):
            urgency = normalize_urgency(stripped[len("URGENCY:"):])
        elif upper.startswith("SUMMARY:"):
            summary = stripped[len("SUMMARY:"):].strip()
        elif summary:
            summary += " " + stripped

    if not summary:
        summary = raw.strip()

    scale_match = re.search(r"[1-5]", relevance)
    relevance_line = f"회사 관계도 {scale_match.group()}/5" if scale_match else relevance
    return title, relevance_line, urgency, urgency_reason, summary, category
