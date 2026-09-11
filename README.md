# Daily News Report

Fetches cybersecurity (and other category) news from **Google News RSS**, summarizes and translates with **Google Gemini**, and delivers results in two ways:

| Product | Audience | Output |
|---------|----------|--------|
| **Email digest** | Recipients on a mailing list | HTML email via Outlook / Office 365 SMTP |
| **Web board** | Local / LAN triage UI | React + FastAPI board with urgency & category scoring |

Shared logic (RSS, article fetch, Gemini, config) lives in `core/`.

---

## How it works

```text
Google News RSS (email) / publisher RSS whitelist (web board)
        →  optional dedupe / history merge  →  Gemini (summary + Korean)
                                                         ↓
                              ┌──────────────────────────┴──────────────────────────┐
                              │                                                      │
                       Email digest HTML                                      Web triage board
                       (SMTP send)                                            (JSON history + UI)
```

1. **Discover** — Google News RSS (search queries and/or the cybersecurity topic feed).
2. **Fetch body** — resolve publisher URLs and pull article text where possible.
3. **Score** — Gemini returns translated title, summary, urgency, and (web board) category.
4. **Deliver** — email HTML, or persist to `data/board_history.json` for the web UI.

---

## Project layout

```text
core/                 Shared models, config, RSS, dedupe, Gemini, article fetch
email_app/            Daily digest: pipeline, HTML builder, SMTP, Tkinter GUI
web_app/              FastAPI API + board prompts (web_app/prompts/)
frontend/             React (Vite + TypeScript) UI for the board
config/               Email categories (e.g. AI/, 보안/) — queries + Gemini prompts
config/*_sites.txt    Optional domain lists (reference / future filtering)
data/                 board_history.json (web board persistence)
gui.py                Shortcut → email digest GUI
```

---

## Setup

### 1. Python

```bash
python -m pip install -r requirements.txt
```

### 2. Environment

Copy `.env.example` → `.env` and set at least:

| Variable | Required for | Notes |
|----------|--------------|--------|
| `GEMINI_API_KEY` | Both | [Google AI Studio](https://aistudio.google.com/app/apikey) |
| `GEMINI_MODEL` | Both | Default `gemini-flash-latest` |
| `SUMMARY_LANGUAGE` | Both | Default `Korean` |
| `SMTP_HOST` / `SMTP_PORT` | Email | e.g. `smtp.office365.com` / `587` |
| `EMAIL_ADDRESS` / `EMAIL_PASSWORD` | Email | App password if MFA is on |
| `EMAIL_TO` | Email (optional) | Fallback recipients; GUI can override |
| `BOARD_RETENTION_DAYS` | Web | Keep articles N days (default `14`) |
| `BOARD_MAX_NEW_SUMMARIES` | Web | Cap Gemini calls per refresh (`0` = no cap) |

### 3. Frontend (web board only)

Requires **Node.js 20+**:

```bash
cd frontend
npm install
```

---

## Email digest

Desktop tool that builds a categorized HTML report and emails it.

### Features

- Category folders under `config/` (e.g. `보안`, `AI`) with Korean/international queries and Gemini prompts
- Tkinter GUI: category, article count, days back, international / Korean feeds, recipients
- Near-duplicate collapse across feeds (`DEDUPE` / `DEDUPE_THRESHOLD`)
- HTML report + SMTP send (Outlook / Office 365)

### Run

```bash
# GUI (recommended)
python gui.py

# Same GUI as a module
python -m email_app.gui

# Headless pipeline (uses defaults / CLI as implemented)
python -m email_app.pipeline

# Quick smoke test
python test_script.py
```

### Config per category

Each folder under `config/<category>/` typically includes:

- `international_query.txt` / `korean_query.txt` — feed label + Google News search query
- `gemini_system_prompt.txt` / `gemini_user_prompt.txt` — digest scoring prompts

Locale for feeds is controlled by `NEWS_LANG`, `NEWS_COUNTRY`, `NEWS_LANG_KR`, `NEWS_COUNTRY_KR` in `.env`.

---

## Web board (CYBER BOARD)

Triage UI for **international cybersecurity** news from a **publisher RSS whitelist**
(`config/international_sites.txt`: `domain | feed_url`) → local JSON history →
Gemini urgency & category → React dashboard.

### Features

- Sources panel: add / remove sites; broken feeds are skipped and shown with an error
- Only articles from the **last 3 days** (`BOARD_ARTICLE_MAX_AGE_DAYS`)
- Title-token dedupe (same as email: `DEDUPE` / `DEDUPE_THRESHOLD`); duplicates skip Gemini
- Urgency dashboard (긴급 / 높음 / 보통 / 낮음) and category dashboard
- Click chart bars / pie slices to filter; search, sort, pagination
- **Refresh** — parallel site RSS fetch, merge by guid, Gemini on new / unscored items
- Per-article **Score now** for deferred items
- Light / dark theme; history under `data/board_history.json`

Board prompts are separate from email: `web_app/prompts/`.

### Dev (hot reload UI)

From the **project root**, two terminals:

```bash
python -m uvicorn web_app.app:app --reload --port 8000

cd frontend
npm run dev
```

Open http://localhost:5173 (Vite proxies API to `:8000`).

### Production / LAN (single URL)

```bash
cd frontend
npm run build

# From project root — not frontend/
cd ..
python -m uvicorn web_app.app:app --host 0.0.0.0 --port 8000
```

- Local: http://127.0.0.1:8000  
- LAN: http://\<your-PC-IP\>:8000  

Allow port **8000** in Windows Firewall if others cannot connect. After UI changes, rebuild `frontend` and hard-refresh the browser.

### Hosted on GitHub Pages (auto-updating)

`.github/workflows/pages.yml` publishes a **read-only** copy of the board to GitHub Pages every 3 hours, on every push to `main`, and on demand:

1. Build the UI in static mode (`npm run build:static`)
2. Restore the previous `api/history.json` from the live site
3. Fetch whitelist RSS feeds and score new articles with Gemini (`python -m web_app.build_static frontend/dist`)
4. Deploy `frontend/dist` to Pages

One-time setup in the GitHub repo:

1. **Settings → Secrets and variables → Actions → New repository secret**: `GEMINI_API_KEY`
2. **Settings → Pages → Build and deployment → Source**: `GitHub Actions`
3. **Actions → Publish board to GitHub Pages → Run workflow**

The hosted page has no Refresh, Score now, or add/remove source buttons — edit `config/international_sites.txt` and push to change sources. Open tabs re-check for new data every 5 minutes. GitHub pauses scheduled workflows in public repos after 60 days without commits; re-enable from the Actions tab.

### API

| Endpoint | Purpose |
|----------|---------|
| `GET /api/health` | Health check |
| `GET /api/articles` | Full history (RSS-only seed if empty) |
| `POST /api/articles/refresh?summarize=true` | Fetch whitelist RSS; optional Gemini |
| `GET /api/articles/{id}` | One article |
| `POST /api/articles/{id}/summarize` | On-demand Gemini for one item |
| `GET /api/sites` | Whitelist + last fetch status |
| `POST /api/sites` | Add site (`domain`, `feed_url`) and fetch |
| `DELETE /api/sites/{domain}` | Remove site and its articles |

Built UI is served from `frontend/dist` at `/` when that folder exists.

---

## Comparison

| | Email digest | Web board |
|--|--------------|-----------|
| **Entry** | `python gui.py` | `uvicorn web_app.app:app` |
| **Feed** | Google News search / topic per category | Publisher RSS whitelist |
| **Prompts** | `config/<category>/` | `web_app/prompts/` |
| **Persistence** | One-shot HTML / email | `data/board_history.json` |
| **Scoring** | Summary + relevance-style fields | Urgency + category (+ Korean summary) |
| **UI** | Tkinter | React |

---

## Notes

- Gemini free-tier pacing uses a minimum interval between calls (`MIN_GEMINI_INTERVAL_SECONDS` in `core/gemini.py`). Large refreshes can take several minutes; use `BOARD_MAX_NEW_SUMMARIES` to cap work per click.
- Always run uvicorn from the **project root** so `web_app` and `frontend/dist` resolve correctly.
- Web board sources live in `config/international_sites.txt` (`domain | feed_url`). Broken feeds are skipped and flagged in the Sources panel. CISA’s feed may return HTTP 403 from some networks — the UI will show that error.
