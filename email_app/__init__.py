"""Daily email digest product: HTML report, SMTP, GUI, pipeline."""

from email_app.pipeline import run_report
from email_app.html_report import build_html
from email_app.send import send_email

__all__ = ["run_report", "build_html", "send_email"]
