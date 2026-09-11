"""Build a static board snapshot for GitHub Pages.

Fetches whitelist RSS feeds, scores pending articles with Gemini (in-process,
not in a background thread), and writes the JSON the static React build reads.

Run from the project root after ``npm run build:static``:

  python -m web_app.build_static frontend/dist
    → frontend/dist/api/articles.json   board payload for the UI
    → frontend/dist/api/history.json    raw history; the next run seeds from it
"""

from __future__ import annotations

import json
import os
import shutil
import sys

from web_app.service import (
    list_board_sites,
    refresh_international_security,
    summarize_pending,
)
from web_app.store import HISTORY_PATH, state_as_dict


def main(argv: list[str]) -> int:
    out_dir = argv[1] if len(argv) > 1 else os.path.join("frontend", "dist")
    api_dir = os.path.join(out_dir, "api")
    os.makedirs(api_dir, exist_ok=True)

    refreshed = refresh_international_security(summarize_new=False)
    ok, failed = summarize_pending()
    print(
        f"  [static] new={refreshed['new_count']} scored={ok} "
        f"failed_or_deferred={failed} total={refreshed['count']}"
    )

    payload = state_as_dict(
        new_count=refreshed["new_count"],
        summarized_count=ok,
        skipped_duplicates=refreshed["skipped_duplicates"],
        feed_errors=refreshed["feed_errors"],
    )
    payload["sites"] = list_board_sites()["sites"]
    with open(os.path.join(api_dir, "articles.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    if os.path.isfile(HISTORY_PATH):
        shutil.copyfile(HISTORY_PATH, os.path.join(api_dir, "history.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
