#!/usr/bin/env python3
"""Runs the syllabus reader on a schedule, on the host that keeps its state (docs/courses.md).

Each run starts from the latest main: it reads the syllabus with the rotation state, rebuilds the
index, validates every dataset the way CI does, and opens a pull request when a
course file changed. The rotation state moves forward only after a run published (or found nothing
to publish), so a failed or held run reads the same files in full again next time.

Every run appends one line to state/runs.jsonl and, when STATUS_URL is set, posts the same line
there (an optional status receiver, e.g. a Cloudflare Worker; STATUS_TOKEN is sent as a bearer
token). GITHUB_TOKEN publishes; RUN_AT (HH:MM, Japan time) schedules. `--once` runs one cycle now.
"""
import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

JAPAN = timezone(timedelta(hours=9))
REPOSITORY = "https://github.com/isct-companion/Isct-Data.git"
REPO = Path(os.environ.get("REPO_DIR", "/data/repo"))
STATE = Path(os.environ.get("STATE_DIR", "/data/state"))


def run(log, *command):
    """One step, its output appended to the run's log; returns its standard output."""
    with log.open("a", encoding="utf-8") as stream:
        stream.write(f"$ {' '.join(command)}\n")
        stream.flush()
        result = subprocess.run(command, cwd=REPO if REPO.exists() else None, text=True,
                                stdout=subprocess.PIPE, stderr=stream)
        stream.write(result.stdout)
    if result.returncode:
        raise RuntimeError(f"{' '.join(command[:3])} exited with {result.returncode}")
    return result.stdout


def cycle():
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / "reader.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return read_and_publish()


def read_and_publish():
    started = datetime.now(JAPAN)
    logs = STATE / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log = logs / f"{started:%Y-%m-%d-%H%M}.log"
    status = {"startedAt": started.isoformat(timespec="seconds"), "ok": False}
    try:
        if not (REPO / ".git").exists():
            run(log, "git", "clone", "--quiet", REPOSITORY, str(REPO))
        run(log, "git", "fetch", "--quiet", "origin", "main")
        run(log, "git", "reset", "--quiet", "--hard", "origin/main")
        run(log, "git", "clean", "-fdq")
        base = run(log, "git", "rev-parse", "HEAD").strip()
        state = STATE / "rotation.json"
        read = run(log, sys.executable, "scripts/syllabus_courses.py", "--state", str(state))
        status["read"] = json.loads(read.strip().splitlines()[-1])
        run(log, sys.executable, "scripts/update_subscription_index.py")
        run(log, sys.executable, "scripts/validate_datasets.py")
        run(log, sys.executable, "scripts/update_subscription_index.py", "--check")
        published = json.loads(run(log, sys.executable, "scripts/syllabus_courses.py", "--publish", base)
                               .strip().splitlines()[-1])
        status["published"] = published
        if "held" in published:
            # An earlier catalog pull request is still open (failed CI or awaits a person).
            status["error"] = f"held behind {published['held']}"
        else:
            state.with_suffix(".pending.json").replace(state)
            status["ok"] = True
    except (OSError, RuntimeError, ValueError, IndexError) as error:
        status["error"] = str(error)
    status["finishedAt"] = datetime.now(JAPAN).isoformat(timespec="seconds")
    status["log"] = log.name
    line = json.dumps(status, ensure_ascii=False)
    with (STATE / "runs.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")
    report(line)
    print(line, flush=True)
    return status["ok"]


def report(line):
    url = os.environ.get("STATUS_URL")
    if not url:
        return
    headers = {"Content-Type": "application/json", "User-Agent": "Isct-Data-syllabus-reader"}
    if os.environ.get("STATUS_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['STATUS_TOKEN']}"
    try:
        urlopen(Request(url, data=line.encode(), headers=headers, method="POST"), timeout=30).close()
    except OSError as error:
        print(f"status report failed: {error}", file=sys.stderr, flush=True)


def next_run(now, at):
    hour, minute = (int(part) for part in at.split(":"))
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return target if target > now else target + timedelta(days=1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="run one cycle now and exit")
    args = parser.parse_args()
    if args.once:
        return 0 if cycle() else 1
    at = os.environ.get("RUN_AT", "03:23")
    while True:
        wake = next_run(datetime.now(JAPAN), at)
        print(f"next run at {wake.isoformat(timespec='minutes')}", flush=True)
        time.sleep(max(0, (wake - datetime.now(JAPAN)).total_seconds()))
        if os.getenv("GITHUB_TOKEN"):
            cycle()
        else:
            print("scheduled publication paused: GITHUB_TOKEN is missing", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
