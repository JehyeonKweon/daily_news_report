"""SMTP send for the daily digest."""

from __future__ import annotations

import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from core.config import parse_email_list
from core.models import LogFn


def send_email(html: str, cfg: dict, log: LogFn = print) -> None:
    if not cfg["email_address"] or not cfg["email_password"]:
        log("  [warn] Email credentials missing; skipping send.")
        return

    recipients = parse_email_list(cfg["email_to"])
    if not recipients:
        log("  [warn] No recipients; skipping send.")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    category = cfg["category"]
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"일일 뉴스 리포트 - {category} - {today}"
    msg["From"] = cfg["email_address"]
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"], local_hostname="localhost") as server:
        server.starttls()
        server.login(cfg["email_address"], cfg["email_password"])
        server.sendmail(cfg["email_address"], recipients, msg.as_string())
        log(f"  Email sent to {', '.join(recipients)}")
