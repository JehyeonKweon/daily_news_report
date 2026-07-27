"""FastAPI app for the international 보안 triage board.

Run from the project root (not frontend/):

  # Dev UI (Vite) + API
  python -m uvicorn web_app.app:app --reload --port 8000

  # LAN / single URL (after: cd frontend && npm run build)
  python -m uvicorn web_app.app:app --host 0.0.0.0 --port 8000
    → http://127.0.0.1:8000  or  http://<your-lan-ip>:8000
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from web_app.service import (
    add_board_site,
    get_score_status,
    list_board_sites,
    refresh_international_security,
    remove_board_site,
    summarize_one,
)
from web_app.store import ensure_loaded, get_state, state_as_dict

_ROOT = Path(__file__).resolve().parents[1]
_FRONTEND_DIST = _ROOT / "frontend" / "dist"

app = FastAPI(
    title="Security News Board",
    description="Whitelist publisher RSS feeds with JSON history + Gemini.",
    version="0.3.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SiteCreate(BaseModel):
    feed_url: str = Field(..., min_length=1)
    domain: str = Field(default="", min_length=0)


@app.on_event("startup")
def _startup() -> None:
    ensure_loaded()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/articles")
def list_articles() -> dict:
    """Return JSON history. If empty, fetch RSS only (no Gemini) so the UI loads fast."""
    ensure_loaded()
    state = get_state()
    if not state.articles:
        return refresh_international_security(summarize_new=False)
    payload = state_as_dict()
    payload["sites"] = list_board_sites()["sites"]
    payload["scoring"] = get_score_status()
    return payload


@app.get("/api/score-status")
def score_status() -> dict:
    return get_score_status()


@app.post("/api/articles/refresh")
def refresh_articles(
    summarize: bool = Query(
        True,
        description="If true, start background Gemini on new / unscored articles.",
    ),
) -> dict:
    """Re-fetch whitelist RSS feeds, dedupe; Gemini runs in background when summarize=true."""
    return refresh_international_security(summarize_new=summarize)


@app.get("/api/articles/{article_id}")
def get_article(article_id: str) -> dict:
    ensure_loaded()
    article = get_state().by_id(article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    return asdict(article)


@app.post("/api/articles/{article_id}/summarize")
def summarize_article(article_id: str) -> dict:
    """On-demand Gemini for one article."""
    try:
        return summarize_one(article_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Article not found") from None
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/sites")
def get_sites() -> dict:
    return list_board_sites()


@app.post("/api/sites")
def create_site(body: SiteCreate) -> dict:
    try:
        # Whitelist only — fetch/score happens on Refresh so Add stays fast.
        return add_board_site(body.domain, body.feed_url, fetch_now=False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/sites/{domain}")
def delete_site(domain: str) -> dict:
    try:
        return remove_board_site(domain)
    except KeyError:
        raise HTTPException(status_code=404, detail="Site not found") from None


# Serve built React UI at / (API routes above take priority).
if _FRONTEND_DIST.is_dir():
    app.mount(
        "/",
        StaticFiles(directory=str(_FRONTEND_DIST), html=True),
        name="ui",
    )


def main() -> None:
    import uvicorn

    uvicorn.run("web_app.app:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    main()
