"""Send the generated ALS Daily Briefing through an environment-configured SMTP server."""

from __future__ import annotations

import argparse
import json
import logging
import os
import smtplib
import ssl
import sys
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
LOGGER = logging.getLogger("als_email")


def truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def new_item_count() -> int:
    total = 0
    for filename in ("articles.json", "trials.json", "news.json"):
        try:
            payload = json.loads((DATA_DIR / filename).read_text(encoding="utf-8"))
            total += len(payload.get("new_keys", []))
        except (OSError, json.JSONDecodeError):
            LOGGER.warning("Could not count new items in %s", filename)
    return total


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Required environment variable {name} is not configured")
    return value


def build_message(html_body: str, count: int) -> EmailMessage:
    sender = require_env("SMTP_FROM")
    recipients = [value.strip() for value in require_env("SMTP_TO").split(",") if value.strip()]
    if not recipients:
        raise ValueError("SMTP_TO does not contain a recipient")
    message = EmailMessage()
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message["Subject"] = f"ALS Global Intelligence Daily Briefing | {datetime.now():%Y-%m-%d} | {count} new"
    message.set_content(
        f"ALS Global Intelligence found {count} new item(s). "
        "This message has an HTML version with source links."
    )
    message.add_alternative(html_body, subtype="html")
    return message


def send(dry_run: bool = False) -> str:
    count = new_item_count()
    if count == 0 and not truthy(os.getenv("SEND_EMPTY_DIGEST")):
        LOGGER.info("No new items; email skipped. Set SEND_EMPTY_DIGEST=true to send empty runs.")
        return "skipped"
    digest_path = DATA_DIR / "email_digest.html"
    html_body = digest_path.read_text(encoding="utf-8")
    if dry_run:
        LOGGER.info("Dry run: email rendered with %d new item(s); SMTP was not contacted.", count)
        return "dry-run"
    host = require_env("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT") or "465")
    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    use_ssl = truthy(os.getenv("SMTP_USE_SSL") or "true")
    use_starttls = truthy(os.getenv("SMTP_USE_STARTTLS") or "false")
    if use_ssl and use_starttls:
        raise ValueError("Choose either SMTP_USE_SSL or SMTP_USE_STARTTLS, not both")
    message = build_message(html_body, count)
    context = ssl.create_default_context()
    smtp_class = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
    with smtp_class(host, port, timeout=30, context=context) if use_ssl else smtp_class(host, port, timeout=30) as client:
        client.ehlo()
        if use_starttls:
            client.starttls(context=context)
            client.ehlo()
        if username:
            client.login(username, password)
        client.send_message(message)
    LOGGER.info("Email sent to %s with %d new item(s).", message["To"], count)
    return "sent"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Validate the digest without contacting SMTP")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        send(dry_run=args.dry_run)
        return 0
    except Exception as exc:
        LOGGER.exception("Email delivery failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
