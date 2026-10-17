import logging
import smtplib
from email.message import EmailMessage

import requests

from .config import env

log = logging.getLogger("kidtube.notify")
LEVELS = {"info": 0, "warning": 1, "critical": 2}
ICON = {"info": "✅", "warning": "⚠️", "critical": "🚨"}


def notify(cfg, level: str, subject: str, body: str = "") -> None:
    """Send alert via Telegram and/or email. Never raises."""
    a = cfg.get("alerts", {})
    if LEVELS.get(level, 0) < LEVELS.get(a.get("min_level", "warning"), 1):
        log.info("alert suppressed (%s): %s", level, subject)
        return
    text = f"{ICON.get(level, '')} KidTube [{level.upper()}] {subject}\n{body}".strip()[:3900]
    if a.get("telegram"):
        try:
            tok, chat = env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_CHAT_ID")
            if tok and chat:
                r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                                  json={"chat_id": chat, "text": text}, timeout=20)
                r.raise_for_status()
            else:
                log.warning("Telegram alerts enabled but TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not set")
        except Exception as e:  # noqa
            log.error("telegram alert failed: %s", e)
    if a.get("email"):
        try:
            host, user, pwd, to = env("SMTP_HOST"), env("SMTP_USER"), env("SMTP_PASSWORD"), env("ALERT_EMAIL_TO")
            if not (host and user and pwd and to):
                log.warning("Email alerts enabled but SMTP_* / ALERT_EMAIL_TO not fully set")
                return
            m = EmailMessage()
            m["Subject"], m["From"], m["To"] = f"[KidTube {level.upper()}] {subject}", user, to
            m.set_content(text)
            port = int(env("SMTP_PORT") or 587)
            smtp = smtplib.SMTP_SSL if port == 465 else smtplib.SMTP
            with smtp(host, port, timeout=30) as s:
                if port != 465:
                    s.starttls()
                s.login(user, pwd)
                s.send_message(m)
        except Exception as e:  # noqa
            log.error("email alert failed: %s", e)
