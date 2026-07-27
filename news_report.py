"""Compatibility shim — prefer `core` and `email_app`.

Run GUI:     python gui.py
Run digest:  python -m email_app.pipeline
Web app:     python -m web_app.app  (placeholder)
"""

from __future__ import annotations

from core import *  # noqa: F403
from email_app.pipeline import main, run_report

if __name__ == "__main__":
    main()
