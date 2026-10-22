"""Invoke once per minute using cron/systemd; do not run automatically during setup."""
from datetime import datetime
import subprocess
import sys
from zoneinfo import ZoneInfo
from .store import connect, now, ROOT, process_lock
from .config import load_local_config


def due(current):
    if current.minute >= 15:
        return None
    return {8: "scan-morning", 17: "scan-afternoon", 18: "digest"}.get(current.hour)


def main():
    load_local_config()
    current = datetime.now(ZoneInfo("Asia/Jerusalem"))
    task = due(current)
    if not task:
        return 0
    with process_lock("scheduler"), connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS scheduled_runs (day TEXT,task TEXT,status TEXT,created_at TEXT,PRIMARY KEY(day,task))")
        day = current.date().isoformat()
        if db.execute("SELECT 1 FROM scheduled_runs WHERE day=? AND task=?", (day, task)).fetchone():
            return 0
        with db:
            db.execute("INSERT INTO scheduled_runs VALUES (?,?,'running',?)", (day, task, now()))
        command = [sys.executable, "-m", "collector.cli", "digest", "--send"] if task == "digest" else [sys.executable, "-m", "collector.cli", "scan"]
        result = subprocess.run(command, cwd=ROOT, check=False)
        with db:
            db.execute("UPDATE scheduled_runs SET status=? WHERE day=? AND task=?", ("ok" if result.returncode == 0 else "failed", day, task))
        return result.returncode


if __name__ == "__main__":
    sys.exit(main())
