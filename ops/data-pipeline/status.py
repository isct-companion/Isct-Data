"""The status page of the data service, served from the runner's own process.

It only reads the run receipts (`runs/<id>/status.json`, `run.log` and the artifacts beside them),
the course rotation state and the scheduler's heartbeat, and turns them into alerts (`alerts`): the
one place that decides whether anything needs the maintainer. `/healthz` answers 503 while a
critical alert stands, so an external uptime monitor can notify without reading the pages. It has no sign-in: Compose publishes it on the NAS's loopback only,
and whatever reaches it from outside (the maintainer's tunnel) must bring its own access control.
The pages themselves are rendered by `status_pages.py`.
"""

from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import threading
from urllib.parse import parse_qs, unquote, urlsplit

import status_pages as pages

JST = timezone(timedelta(hours=9))
RUN_ID = re.compile(r"nas-\d{8}-\d{6}-[0-9a-f]{8}")
LOG_LIMIT = 1024 * 1024
TEXT_FILES = {".json", ".jsonl", ".md", ".txt", ".log", ".csv"}
HISTORY_DAYS = 30
LIVE_LINES = 200  # log lines a running run's page shows; the overview shows the last dozen
SUCCESS = {"published", "unchanged", "checked", "ok"}
HEARTBEAT_LATE = timedelta(minutes=5)  # the scheduler ticks every minute while no run holds it
RUN_LATE = timedelta(hours=2)  # every command has its own 15-minute timeout; a run this long is stuck
ROTATION_LATE_DAYS = 35  # syllabus_courses.ROTATION_DAYS plus a few days of failed runs
OFFERING_DROP = 0.1  # a syllabus read that loses this share of offerings is a site change, not a term


def moment(value):
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed.astimezone(JST) if parsed.tzinfo else None


def read_record(path):
    try:
        with path.open("rb") as file:
            value = json.loads(file.read(4 * 1024 * 1024))
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict) or not moment(value.get("startedAt")):
        return None
    value["run"] = path.parent.name
    if "job" not in value:  # receipts written before the runner was one service
        value["job"] = value.get("dataset") if value.get("action") == "update" else value.get("action")
    return value if value.get("job") in pages.JOBS and value.get("status") in pages.STATES else None


def records(runs):
    """Every readable run record, newest first."""
    found = filter(None, (read_record(path) for path in Path(runs).glob("nas-*/status.json")))
    return sorted(found, key=lambda record: record["startedAt"], reverse=True)


def seconds(record):
    start, end = moment(record.get("startedAt")), moment(record.get("finishedAt"))
    return int((end - start).total_seconds()) if start and end else None


def daily(mine, now, days=HISTORY_DAYS, checks=None):
    """The last run of each of the last `days` days, oldest day first (`mine` is newest first), with
    that day's source check counts."""
    by_day = {}
    for record in reversed(mine):  # oldest first, so the day keeps its last run
        by_day[moment(record["startedAt"]).date().isoformat()] = record
    counts = (checks or {}).get("days") or {}
    return [{"day": day.isoformat(), "record": by_day.get(day.isoformat()), "checks": counts.get(day.isoformat())}
            for day in (now.date() - timedelta(days=offset) for offset in range(days - 1, -1, -1))]


def period(rule):
    if rule.get("every"):
        return timedelta(minutes=rule["every"])
    return timedelta(days=7 if rule.get("weekday") is not None else 1)


def read_checks(path):
    """Each dataset's last source check (`runner.check`), by job."""
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def last_current(mine, entry):
    """When the published data was last known to match the sources: a successful run, or a check
    that found nothing to review. Returns (moment, record or None)."""
    success = next((record for record in mine if record["status"] in SUCCESS), None)
    ran = moment(success.get("finishedAt") or success["startedAt"]) if success else None
    checked = moment((entry or {}).get("lastCurrent"))
    if checked and (not ran or checked > ran):
        return checked, None
    return ran, success


def age(delta):
    hours = int(delta.total_seconds() // 3600)
    return f"{hours} 小时" if hours < 48 else f"{hours // 24} 天"


def verified_dates(rotation):
    """Each course file's last full read (listing in English and every detail page), by file."""
    try:
        verified = json.loads(Path(rotation).read_text(encoding="utf-8")).get("verified", {})
    except (OSError, ValueError, AttributeError):
        return {}
    return verified if isinstance(verified, dict) else {}


def token_limit():
    try:
        return int(os.getenv("OPENAI_RUN_TOKEN_LIMIT", ""))
    except ValueError:
        return None


def alert(level, title, detail="", job=None, record=None, since=None):
    return {"level": level, "job": job, "title": title, "detail": detail,
            "run": record["run"] if record else None, "since": since or (record or {}).get("startedAt")}


def job_alerts(job, rule, mine, plan, now, limit, entry=None):
    """What needs a person in one scheduled job: stopped, stale, failing, or reading a changed site."""
    if (plan or {}).get("paused"):
        return [alert("critical", "已暂停", f"{plan['paused']}，补上后自动恢复", job)]
    finished = [record for record in mine if record["status"] not in ("running", "held")]
    found = []
    if entry and entry.get("failures", 0) >= 3:
        found.append(alert("warning", f"来源检查连续失败 {entry['failures']} 次", entry.get("error") or "", job,
                           since=entry.get("at")))
    if not finished and not entry:
        return found
    current, success = last_current(mine, entry)
    streak = []
    for record in finished:
        if record["status"] in SUCCESS:
            break
        streak.append(record)
    allowed = 2 * period(rule) + timedelta(hours=6)  # two missed checks or runs, then the data is old
    error = (streak[0].get("error") or "")[:300] if streak else ""
    if not current:
        if streak:
            found.append(alert("critical", "从未成功", error, job, streak[0]))
    elif now - current > allowed:
        found.append(alert("critical", f"数据 {age(now - current)}没有确认", error or "没有新的成功运行或检查", job,
                           streak[0] if streak else success, current.isoformat(timespec="seconds")))
    elif streak and (len(streak) >= 2 or streak[0]["status"] != "retry"):
        hard = any(record["status"] != "retry" for record in streak)
        found.append(alert("critical" if hard and len(streak) >= 2 else "warning",
                           f"连续 {len(streak)} 次未成功" if len(streak) >= 2 else "最近一次失败",
                           error, job, streak[0], streak[-1]["startedAt"]))
    if finished:
        last = finished[0]
        removed = sum(source["change"] == "removed" for source in last.get("sources") or [])
        if removed:
            found.append(alert("warning", f"{removed} 个官方来源消失", "学校网页可能改了地址或结构，检查来源清单", job, last))
        if limit and (last.get("tokens") or 0) > limit:
            found.append(alert("warning", "超出 token 上限", f"{last['tokens']:,} / {limit:,}", job, last))
    return found


def course_alerts(mine, verified, now):
    """The syllabus job's own risks: a read that lost many offerings, and files not re-read in time."""
    found = []
    counted = [record for record in mine if record.get("courseFiles") and record["status"] in SUCCESS]
    if len(counted) >= 2:
        latest, before = (sum(record["courseFiles"].values()) for record in counted[:2])
        if before and latest < before * (1 - OFFERING_DROP):
            found.append(alert("critical", "开讲科目数骤减", f"{before:,} → {latest:,}，Syllabus 的页面结构可能变了",
                               "courses", counted[0]))
    oldest = min(verified.values(), default=None)
    if oldest:
        days = (now.date() - date.fromisoformat(oldest)).days
        if days > ROTATION_LATE_DAYS:
            found.append(alert("warning", f"有课程文件 {days} 天没有重读详情页",
                               f"轮转应在 30 天内读完所有文件，最早的是 {oldest}", "courses", since=oldest))
    return found


def alerts(found, schedule, plan, verified, heartbeat, now, limit=None, checks=None):
    """Every standing alert, critical first: the one judgement of whether anything needs a person."""
    raised = []
    running = [record for record in found if record["status"] == "running"]
    for record in running:
        if now - moment(record["startedAt"]) > RUN_LATE:
            raised.append(alert("critical", "运行超过 2 小时", "可能卡在某一步，看运行详情的步骤", record["job"], record))
    if not running and (not heartbeat or now - heartbeat > HEARTBEAT_LATE):
        raised.append(alert("critical", "调度器没有心跳",
                            "服务可能已停止或卡住" if heartbeat else "还没有心跳记录，服务可能没有以 serve 启动",
                            since=heartbeat.isoformat(timespec="seconds") if heartbeat else None))
    for job, rule in schedule.items():
        mine = [record for record in found if record["job"] == job]
        raised += job_alerts(job, rule, mine, plan.get(job), now, limit, (checks or {}).get(job))
        if job == "courses" and not (plan.get(job) or {}).get("paused"):
            raised += course_alerts(mine, verified, now)
    return sorted(raised, key=lambda item: item["level"] != "critical")


def read_heartbeat(path):
    try:
        return moment(json.loads(Path(path).read_text(encoding="utf-8")).get("at"))
    except (OSError, ValueError, AttributeError, TypeError):
        return None


def health(raised):
    return "critical" if any(item["level"] == "critical" for item in raised) else "warning" if raised else "ok"


def overview(found, schedule, plan, verified, heartbeat, now, checks=None):
    """The front page: overall health and its alerts, then one row per job with its last 30 days."""
    checks = checks or {}
    raised = alerts(found, schedule, plan, verified, heartbeat, now, token_limit(), checks)
    rows = []
    for name in [*schedule, *sorted({record["job"] for record in found} - set(schedule))]:
        mine = [record for record in found if record["job"] == name]
        month = [record for record in mine if now - moment(record["startedAt"]) <= timedelta(days=HISTORY_DAYS)]
        done = [record for record in month if record["status"] != "running"]
        current, _ = last_current(mine, checks.get(name))
        rows.append({"job": name, "scheduled": name in schedule, "last": mine[0] if mine else None,
                     "current": current.isoformat(timespec="seconds") if current else None,
                     "check": {key: value for key, value in (checks.get(name) or {}).items() if key != "days"} or None,
                     "every": (schedule.get(name) or {}).get("every"),
                     "health": health([item for item in raised if item["job"] == name]),
                     "calendar": daily(mine, now, checks=checks.get(name)), "plan": plan.get(name),
                     "success": [sum(record["status"] in SUCCESS for record in done), len(done)]})
    week = [record for record in found if now - moment(record["startedAt"]) <= timedelta(days=7)]
    return {"generatedAt": now.isoformat(timespec="seconds"), "health": health(raised), "alerts": raised,
            "heartbeat": heartbeat.isoformat(timespec="seconds") if heartbeat else None,
            "jobs": rows, "running": [record for record in found if record["status"] == "running"],
            "week": {"runs": len(week), "failed": sum(record["status"] in pages.FAILED for record in week),
                     "published": sum(record["status"] == "published" for record in week),
                     "requests": sum(record.get("requests") or 0 for record in week),
                     "tokens": sum(record.get("tokens") or 0 for record in week)},
            "recent": found[:8]}


def run_list(found, now, job=None, state=None):
    listed = [record for record in found
              if (not job or record["job"] == job) and (not state or record["status"] == state)]
    return {"generatedAt": now.isoformat(timespec="seconds"), "filter": {"job": job, "status": state},
            "jobs": sorted({record["job"] for record in found}, key=list(pages.JOBS).index),
            "runs": listed[:200], "matching": len(listed)}


def history(found, job, plan, now, days=HISTORY_DAYS, checks=None):
    """One job over the last `days` days: the last result of each day and every run's figures."""
    since = now - timedelta(days=days)
    mine = [record for record in found if record["job"] == job and moment(record["startedAt"]) >= since]
    entry = (checks or {}).get(job)
    return {"job": job, "plan": plan.get(job), "days": days, "calendar": daily(mine, now, days, entry),
            "check": {key: value for key, value in (entry or {}).items() if key != "days"} or None,
            "runs": mine, "series": [{"run": record["run"], "at": record["startedAt"], "status": record["status"],
                                      "seconds": seconds(record), "requests": record.get("requests"),
                                      "tokens": record.get("tokens")} for record in reversed(mine)]}


def courses(found, rotation, now, days=HISTORY_DAYS):
    """The course rotation: each file's full reads over the last `days` days and recent changes."""
    verified = verified_dates(rotation)
    since = now.date() - timedelta(days=days - 1)
    mine = [record for record in found if record["job"] == "courses"]
    latest = next((record for record in mine if record.get("courseFiles")), None)
    counts = (latest or {}).get("courseFiles") or {}
    names = (latest or {}).get("courseNames") or {}
    reads, changed = {}, {}
    for record in mine:
        day = moment(record["startedAt"]).date()
        if day < since:
            continue
        for year in record.get("years") or []:
            for name in year.get("readInFull") or []:
                reads.setdefault(name, set()).add(day.isoformat())
        for change in record.get("changes") or []:
            changed.setdefault(change["file"], set()).add(day.isoformat())
    files = sorted({*verified, *counts}, key=lambda name: (verified.get(name) or "", name))
    covered = sum(1 for name in files if (verified.get(name) or "") >= since.isoformat())
    return {"days": [(since + timedelta(days=offset)).isoformat() for offset in range(days)],
            "files": [{"file": name, "name": names.get(name), "offerings": counts.get(name),
                       "verified": verified.get(name), "reads": sorted(reads.get(name, ())), "changed": sorted(changed.get(name, ()))}
                      for name in files],
            "summary": {"files": len(files), "offerings": sum(counts.values()), "covered": covered,
                        "oldest": min((verified[name] for name in files if verified.get(name)), default=None),
                        "unverified": sum(1 for name in files if not verified.get(name))},
            "latest": latest, "changes": [record for record in mine if record.get("changes")][:20]}


def receipt_files(directory):
    """The artifacts a run kept beside its record, as (relative path, bytes, viewable)."""
    listed = []
    for path in sorted(Path(directory).rglob("*")):
        if path.is_file() and path.name not in ("status.json", "run.log"):
            listed.append({"path": path.relative_to(directory).as_posix(), "bytes": path.stat().st_size,
                           "text": path.suffix in TEXT_FILES})
    return listed[:200]


def log_tail(path, lines=60):
    try:
        with Path(path).open("rb") as file:
            file.seek(max(0, file.seek(0, 2) - 64 * 1024))
            return file.read().decode("utf-8", "replace").splitlines()[-lines:]
    except OSError:
        return []


def with_log(runs, record, lines):
    """A running record with the end of its log, for the pages that follow it live."""
    return {**record, "logTail": log_tail(Path(runs) / record["run"] / "run.log", lines)}


def detail(runs, run_id, now):
    directory = Path(runs) / run_id
    record = read_record(directory / "status.json")
    if not record:
        return None
    running = record["status"] == "running"
    if running:
        record = with_log(runs, record, LIVE_LINES)
    return {"record": record, "files": receipt_files(directory), "generatedAt": now.isoformat(timespec="seconds"),
            "hasLog": (directory / "run.log").is_file(),
            "logTail": log_tail(directory / "run.log") if record["status"] in pages.FAILED else []}


def safe_file(runs, run_id, relative):
    """A text artifact inside the run's own folder, or None."""
    directory = (Path(runs) / run_id).resolve()
    target = (directory / relative).resolve()
    if directory not in target.parents or target.suffix not in TEXT_FILES or not target.is_file():
        return None
    return target


# -- Server -------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlsplit(self.path)
        parts = [unquote(part) for part in url.path.strip("/").split("/")] if url.path.strip("/") else []
        query = {key: values[0] for key, values in parse_qs(url.query).items()}
        server, now = self.server, datetime.now(JST)
        if parts in ([], ["api", "status"], ["healthz"]):
            view = overview(records(server.runs), server.schedule, server.upcoming(),
                            verified_dates(server.rotation), read_heartbeat(server.heartbeat), now,
                            read_checks(server.checks))
            view["running"] = [with_log(server.runs, record, 12) for record in view["running"]]
            if parts == ["healthz"]:
                critical = [f'{pages.JOBS[item["job"]] if item["job"] else "数据服务"}：{item["title"]}'
                            for item in view["alerts"] if item["level"] == "critical"]
                return self.reply(503 if critical else 200, ("\n".join(critical) or "ok").encode() + b"\n")
            if parts:
                return self.reply(200, json.dumps(view, ensure_ascii=False).encode(), "application/json")
            return self.reply(200, pages.overview(view), "text/html")
        if parts == ["runs"]:
            job = query.get("job") if query.get("job") in pages.JOBS else None
            state = query.get("status") if query.get("status") in pages.STATES else None
            return self.reply(200, pages.runs(run_list(records(server.runs), now, job, state)), "text/html")
        if len(parts) == 2 and parts[0] == "jobs" and parts[1] in pages.JOBS:
            found, plan, checks = records(server.runs), server.upcoming(), read_checks(server.checks)
            view = history(found, parts[1], plan, now, checks=checks)
            view["alerts"] = [item for item in alerts(found, server.schedule, plan, verified_dates(server.rotation),
                                                      read_heartbeat(server.heartbeat), now, token_limit(), checks)
                              if item["job"] == parts[1]]
            view["running"] = [with_log(server.runs, record, 12) for record in found
                               if record["job"] == parts[1] and record["status"] == "running"]
            return self.reply(200, pages.history(view, now), "text/html")
        if parts == ["courses"]:
            view = courses(records(server.runs), server.rotation, now)
            return self.reply(200, pages.courses(view), "text/html")
        if len(parts) >= 2 and parts[0] == "runs" and RUN_ID.fullmatch(parts[1]):
            if len(parts) == 2:
                view = detail(server.runs, parts[1], now)
                return (self.reply(200, pages.detail(view), "text/html") if view
                        else self.reply(404, b"no such run\n"))
            if parts[2:] == ["log"]:
                return self.send_log(server.runs / parts[1] / "run.log")
            if parts[2] == "files" and len(parts) > 3:
                target = safe_file(server.runs, parts[1], "/".join(parts[3:]))
                if target:
                    return self.reply(200, target.read_bytes()[:LOG_LIMIT])
        self.reply(404, b"not found\n")

    def send_log(self, path):
        try:
            with path.open("rb") as file:
                size = file.seek(0, 2)
                file.seek(max(0, size - LOG_LIMIT))
                data = file.read()
        except OSError:
            return self.reply(404, b"no log for this run\n")
        if size > LOG_LIMIT:
            data = f"[showing the last {LOG_LIMIT} of {size} bytes]\n".encode() + data
        self.reply(200, data)

    def reply(self, status, data, mime="text/plain"):
        self.send_response(status)
        self.send_header("Content-Type", mime + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; style-src 'unsafe-inline'; img-src data:; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_):
        pass


def start(runs, rotation, schedule, upcoming, heartbeat, checks, port=8787):
    """Serves the pages on a daemon thread; the container's port mapping decides who reaches them."""
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    server.daemon_threads = True
    server.runs, server.rotation, server.heartbeat, server.checks = Path(runs), Path(rotation), Path(heartbeat), Path(checks)
    server.schedule, server.upcoming = schedule, upcoming
    threading.Thread(target=server.serve_forever, name="status", daemon=True).start()
    return server
