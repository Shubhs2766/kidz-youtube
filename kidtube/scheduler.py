import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import path_of, today_str, tz
from .db import DB, SUCCESS
from .notify import notify
from .pipeline import run_day

log = logging.getLogger("kidtube.scheduler")
DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def job_daily(cfg):
    date = today_str(cfg)
    log.info("Scheduled run starting for %s", date)
    run_day(cfg, date)


def job_watchdog(cfg):
    date = today_str(cfg)
    r = DB(path_of(cfg, "db_file")).latest_run(date)
    if not r or r["status"] not in SUCCESS:
        notify(cfg, "critical", f"Watchdog: no finished video for {date}", f"Latest run status: {r['status'] if r else 'no run at all'}")


def missing_scripts(cfg, days=7):
    base = datetime.now(tz(cfg))
    miss = []
    for i in range(1, days + 1):
        d = (base + timedelta(days=i)).strftime("%Y-%m-%d")
        if not (path_of(cfg, "scripts_dir") / f"{d}.txt").exists():
            miss.append(d)
    return miss


def job_weekly(cfg):
    runs = DB(path_of(cfg, "db_file")).recent_runs(7)
    lines = [f"{r['date']}: {r['status']} ${r['est_cost'] or 0:.2f} {r['title'] or ''}" for r in runs]
    miss = missing_scripts(cfg)
    body = "Last runs:\n" + "\n".join(lines) + ("\n\nMissing script files for the next 7 days:\n" + ", ".join(miss) if miss else "\n\nAll next-7-days scripts are present.")
    notify(cfg, "warning" if miss else "info", "Weekly report", body)


def serve(cfg):
    hh, mm = map(int, cfg["schedule"]["time"].split(":"))
    zone = tz(cfg)
    sch = BlockingScheduler(timezone=zone)
    sch.add_job(job_daily, CronTrigger(hour=hh, minute=mm, timezone=zone), args=[cfg], id="daily", misfire_grace_time=3600, coalesce=True)
    wd = (datetime(2000, 1, 1, hh, mm) + timedelta(minutes=int(cfg["schedule"].get("watchdog_minutes", 180))))
    sch.add_job(job_watchdog, CronTrigger(hour=wd.hour, minute=wd.minute, timezone=zone), args=[cfg], id="watchdog")
    wh, wm = map(int, cfg["schedule"].get("weekly_report_time", "18:00").split(":"))
    sch.add_job(job_weekly, CronTrigger(day_of_week=cfg["schedule"].get("weekly_report_day", "sun"), hour=wh, minute=wm, timezone=zone), args=[cfg], id="weekly")
    log.info("Scheduler running: daily at %s %s. Press Ctrl+C to stop.", cfg["schedule"]["time"], cfg["schedule"]["timezone"])
    try:
        sch.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped")
