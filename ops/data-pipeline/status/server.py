"""Read-only status view protected by a Cloudflare Access application token."""

import html
import json
import os
import re
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import jwt

STATE = Path("/status")
JST = timezone(timedelta(hours=9))
ISSUER_PATTERN = re.compile(r"https://[a-z0-9][a-z0-9-]*\.cloudflareaccess\.com")
AUDIENCE_PATTERN = re.compile(r"[a-fA-F0-9]{64}")
LABELS = {
    "validate": "全量校验", "exams": "考试日程", "academic-calendar": "校历",
    "important-dates": "重要日程", "departments": "院系与履修", "syllabus": "Syllabus 抓取",
}
STATES = {"ok": "完成", "failed": "失败", "running": "进行中", "stale": "未记录完成", "waiting": "暂无记录"}


class Access:
    def __init__(self, issuer, audience, emails):
        self.issuer = issuer.rstrip("/")
        self.audience = audience
        self.emails = {email.strip().casefold() for email in emails.split(",") if email.strip()}
        self.keys = None
        if ISSUER_PATTERN.fullmatch(self.issuer) and AUDIENCE_PATTERN.fullmatch(audience) and self.emails:
            self.keys = jwt.PyJWKClient(self.issuer + "/cdn-cgi/access/certs", timeout=5)

    def authorizes(self, token):
        if not self.keys or not token or len(token) > 16384:
            return False
        try:
            if jwt.get_unverified_header(token).get("alg") != "RS256":
                return False
            signing_key = self.keys.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token, signing_key.key, algorithms=["RS256"], issuer=self.issuer, audience=self.audience,
                options={"require": ["iss", "aud", "iat", "exp", "email"]},
            )
        except (jwt.PyJWTError, OSError, ValueError, TypeError):
            return False
        email = claims["email"]
        return isinstance(email, str) and email.casefold() in self.emails


def dated(value):
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment.astimezone(JST) if moment.tzinfo else None


def status_row(kind, state, started=None, finished=None, commit=None):
    if state not in STATES or not started:
        return {"kind": kind, "status": "waiting", "at": None, "commit": None}
    if state == "running" and datetime.now(JST) - started > timedelta(hours=3):
        state = "stale"
    commit = commit[:7] if isinstance(commit, str) and re.fullmatch(r"[a-f0-9]{40}", commit) else None
    return {"kind": kind, "status": state, "at": (finished or started).isoformat(timespec="seconds"),
            "commit": commit}


def read_record(path):
    try:
        with path.open("rb") as file:
            value = json.loads(file.read(8192))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def collect(root=STATE):
    latest = {}
    for directory in (root / "ci").glob("nas-*"):
        record = read_record(directory / "status.json")
        kind = record.get("dataset") if record.get("action") == "update" else record.get("action")
        started = dated(record.get("startedAt"))
        if kind in LABELS and started and (kind not in latest or started > latest[kind][0]):
            latest[kind] = (started, record)

    rows = []
    for kind in LABELS:
        if kind == "syllabus":
            syllabus = last_syllabus(root / "syllabus.jsonl")
            rows.append(status_row(kind, "ok" if syllabus.get("ok") is True else "failed",
                                   dated(syllabus.get("startedAt")), dated(syllabus.get("finishedAt"))))
        elif kind in latest:
            started, record = latest[kind]
            rows.append(status_row(kind, record.get("status"), started,
                                   dated(record.get("finishedAt")), record.get("base")))
        else:
            rows.append(status_row(kind, "waiting"))
    return rows


def last_syllabus(path):
    try:
        with path.open("rb") as file:
            offset = max(0, file.seek(0, 2) - 65536)
            file.seek(offset)
            lines = file.read(65536).splitlines()
    except OSError:
        return {}
    for line in reversed(lines):
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return {}


def dashboard(rows):
    cards = []
    for row in rows:
        label = LABELS[row["kind"]]
        state = row["status"]
        at = dated(row["at"])
        when = at.strftime("%Y-%m-%d %H:%M") + " JST" if at else "—"
        commit = f'<code>{html.escape(row["commit"])}</code>' if row["commit"] else ""
        cards.append(f'<article><h2>{label}</h2><p class="{state}">{STATES[state]}</p>'
                     f'<footer>{when} {commit}</footer></article>')
    return ("""<!doctype html><html lang="zh-Hans"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Isct-Data 运行状态</title>
<style>
* {box-sizing:border-box} body {margin:0;background:#11181d;color:#e9f0ef;font:1rem system-ui,sans-serif}
main {width:min(56rem,100%);margin:auto;padding:clamp(1.5rem,6vw,4rem)}
h1 {margin:0 0 .6rem;font-size:clamp(1.8rem,6vw,2.75rem);letter-spacing:-.045em}
header p,footer {color:#aac3c1} header {margin-bottom:2rem}
section {display:grid;grid-template-columns:repeat(auto-fit,minmax(min(14rem,100%),1fr));gap:1rem}
article {background:#1c292e;border:1px solid #375056;border-radius:.8rem;padding:1.15rem;min-height:8rem}
h2 {margin:0;font-size:1.1rem} article p {margin:.55rem 0 .7rem;font-weight:650}
.ok {color:#8be5b5}.failed {color:#ffac9f}.running {color:#ade5fb}.stale {color:#f7d18b}
footer {font-variant-numeric:tabular-nums;font-size:.875rem} code {margin-left:.35rem}
</style>
<main><header><h1>Isct-Data 运行状态</h1><p>NAS 校验、定时更新和抓取的最近一次记录。</p></header><section>
""" + "".join(cards) + "</section></main></html>").encode()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/healthz":
            self.reply(200, b"ok\n")
        elif path not in {"/", "/api/status"}:
            self.reply(404, b"Not found\n")
        elif not self.server.access.keys:
            self.reply(503, b"Cloudflare Access configuration required\n")
        elif not self.server.access.authorizes(self.headers.get("Cf-Access-Jwt-Assertion")):
            self.reply(401, b"Cloudflare Access email sign-in required\n")
        else:
            rows = collect()
            if path == "/api/status":
                self.reply(200, json.dumps(rows, ensure_ascii=False).encode(), "application/json")
            else:
                self.reply(200, dashboard(rows), "text/html")

    def reply(self, status, data, mime="text/plain"):
        self.send_response(status)
        self.send_header("Content-Type", mime + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    app = ThreadingHTTPServer(("0.0.0.0", 8787), Handler)
    app.access = Access(os.getenv("CF_ACCESS_ISSUER", ""), os.getenv("CF_ACCESS_AUDIENCE", ""),
                        os.getenv("CF_ACCESS_EMAILS", ""))
    app.serve_forever()
