import argparse
import logging
import shutil
import sys
from datetime import datetime, timedelta

from .config import env, load_config, path_of, today_str, tz
from .db import DB
from .logging_setup import setup_logging


def doctor(cfg) -> int:
    ok = True

    def chk(name, cond, hint=""):
        nonlocal ok
        print(("  OK   " if cond else "  FAIL ") + name + ("" if cond else f"  -> {hint}"))
        ok = ok and cond

    print("Checking setup...")
    chk("ffmpeg installed", shutil.which("ffmpeg") is not None, "install ffmpeg and add it to PATH")
    chk("ffprobe installed", shutil.which("ffprobe") is not None, "comes with ffmpeg")
    chk("GEMINI_API_KEY", bool(env("GEMINI_API_KEY")), "set in .env")
    if cfg["alerts"].get("telegram"):
        chk("Telegram token + chat id", bool(env("TELEGRAM_BOT_TOKEN") and env("TELEGRAM_CHAT_ID")), "set in .env")
    if cfg["alerts"].get("email"):
        email_settings = all(env(key) for key in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "ALERT_EMAIL_TO"))
        chk("Email alert settings", email_settings, "set SMTP_HOST, SMTP_USER, SMTP_PASSWORD and ALERT_EMAIL_TO in .env")
        chk("SMTP port", env("SMTP_PORT") in ("465", "587"), "use 465 (implicit SSL) or 587 (STARTTLS)")
    from .youtube import _p
    chk("YouTube client_secret.json", _p(cfg, "client_secret_file").exists(), "download OAuth desktop client JSON (README step 4)")
    chk("YouTube token (run `auth`)", _p(cfg, "token_file").exists(), "python -m kidtube auth")
    sd = path_of(cfg, "scripts_dir")
    chk(f"scripts dir exists ({sd})", sd.exists())
    d = today_str(cfg)
    chk(f"script for today ({d}.txt) or backlog", (sd / f"{d}.txt").exists() or any(path_of(cfg, "backlog_dir").glob("*.txt")), "add the file")
    print("All good." if ok else "Some checks failed (see above).")
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(prog="kidtube", description="Automated kids' AI video channel")
    ap.add_argument("--config", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor", help="check installation/config")
    sub.add_parser("auth", help="one-time YouTube OAuth login")
    r = sub.add_parser("run", help="run the pipeline once")
    r.add_argument("--date", help="YYYY-MM-DD (default: today in configured timezone)")
    r.add_argument("--dry-run", action="store_true", help="offline test with mock providers, no upload")
    r.add_argument("--api-test", action="store_true", help="use free-tier Gemini for a short test; mock visuals, no music or upload")
    r.add_argument("--force", action="store_true", help="redo even if already done")
    sub.add_parser("serve", help="stay running and execute daily at schedule.time")
    p = sub.add_parser("publish", help="make an approved private video public")
    p.add_argument("date")
    sub.add_parser("status", help="show recent runs")
    sub.add_parser("weekly-report", help="send the weekly report now")
    a = ap.parse_args(argv)

    cfg = load_config(a.config)
    setup_logging(path_of(cfg, "logs_dir"))
    if a.cmd == "doctor":
        sys.exit(doctor(cfg))
    if a.cmd == "auth":
        from . import youtube
        youtube.authorize(cfg)
        youtube.check_channel(cfg)
    elif a.cmd == "run":
        from .pipeline import run_day
        date = a.date or today_str(cfg)
        datetime.strptime(date, "%Y-%m-%d")
        if a.dry_run and a.api_test:
            ap.error("--dry-run and --api-test cannot be used together")
        sys.exit(0 if run_day(cfg, date, dry_run=a.dry_run, force=a.force, api_test=a.api_test) else 1)
    elif a.cmd == "serve":
        from .scheduler import serve
        serve(cfg)
    elif a.cmd == "publish":
        from .pipeline import publish_video
        publish_video(cfg, a.date)
    elif a.cmd == "status":
        for r in DB(path_of(cfg, "db_file")).recent_runs(20):
            print(f"{r['date']}  {r['status']:<18} {'dry ' if r['dry_run'] else '    '}${r['est_cost'] or 0:>5.2f}  {r['video_url'] or '-':<28} {r['title'] or ''}"
                  + (f"\n      error: {r['error'][:150]}" if r["error"] else ""))
    elif a.cmd == "weekly-report":
        from .scheduler import job_weekly
        job_weekly(cfg)
