# Daily News Report

Fetches the top trending news per topic from **Google News RSS**, summarizes each
article with **Google Gemini**, and emails a clean HTML report via **Outlook/SMTP**.

Each item includes the **name (title)**, an **AI summary**, and a **link** to the article.

## Setup

1. Install dependencies:

   ```bash
   python -m pip install -r requirements.txt
   ```

2. Create your config from the template:

   ```bash
   copy .env.example .env
   ```

3. Edit `.env`:
   - `TOPICS` — comma-separated topics you care about.
   - `GEMINI_API_KEY` — free key from https://aistudio.google.com/app/apikey
   - `EMAIL_ADDRESS` / `EMAIL_PASSWORD` — your Outlook account.
     - If your account has MFA, create an **app password** and use that.
   - `EMAIL_TO` — recipient (defaults to your own address).

## Usage

```bash
python news_report.py
```

This fetches news, summarizes it, saves a local copy to `latest_report.html`,
and emails the report.

### Quick test (no API key or email needed)

```bash
python test_script.py
```

Verifies that fetching and link resolution work for one topic.

## Notes

- **Summaries**: the script fetches each article's text and asks Gemini for a
  2–3 sentence summary. If article text can't be fetched, it summarizes from the
  headline. Without a Gemini key, raw headlines are used.
- **Links**: Google News uses encoded redirect URLs; these are decoded to the
  real publisher URL when possible.
- **Cost**: Google News RSS is free. Gemini has a generous free tier
  (`gemini-2.0-flash`). Outlook sending is free.

## Run it automatically (optional, Windows)

Use Task Scheduler to run daily:

1. Open **Task Scheduler** → **Create Basic Task**.
2. Trigger: **Daily**, pick a time.
3. Action: **Start a program**
   - Program: `python`
   - Arguments: `news_report.py`
   - Start in: this project folder.
