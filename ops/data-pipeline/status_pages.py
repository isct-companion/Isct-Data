"""HTML for the data service's status pages (`status.py` collects what they show).

Plain server-rendered HTML with no script: hovering a mark shows its native tooltip, and every
chart has the same figures in a table beside it. Colours are role tokens: status colours only ever
mark a run's result and always sit next to its label.
"""

from datetime import datetime, timedelta, timezone
import html
from urllib.parse import urlencode

REPO_URL = "https://github.com/isct-companion/Isct-Data"
JST = timezone(timedelta(hours=9))
JOBS = {
    "courses": "开讲科目（Syllabus）", "exams": "期末考试与考试周授课", "academic-calendar": "校历",
    "important-dates": "重要日程", "departments": "学系与履修指南",
    "candidates": "考试候补补丁（手动）", "shadow": "考试 PDF 分页比对（手动）", "validate": "全量校验（已停用）",
}
# status: (label, tone, what it means)
STATES = {
    "published": ("已发布", "good", "校验通过的变化已推到 main"),
    "unchanged": ("无变化", "neutral", "读完来源，数据没有变化"),
    "checked": ("已检查", "quiet", "只检查了来源，没有审核或发布"),
    "ok": ("完成", "good", "旧版运行记录"),
    "retry": ("保留", "warning", "校验期间 main 前进了，下次从新的 main 重跑"),
    "failed": ("失败", "critical", "运行出错，没有发布"),
    "interrupted": ("中断", "serious", "服务重启时运行尚未结束"),
    "running": ("进行中", "running", "正在运行"),
}
FAILED = {"failed", "interrupted", "retry"}
SOURCE_CHANGES = {
    "content": ("可见内容有变", "warning"), "bytes": ("仅标记或编码变化", "neutral"),
    "new": ("新增来源", "warning"), "removed": ("来源消失", "serious"), "same": ("未变", "quiet"),
}
NOTES = {  # source_monitor.triage's reasons
    "no reviewed source baseline is committed yet": "还没有已审核的来源基线",
    "source manifests changed": "来源清单有变",
    "the set of official sources changed": "官方来源的文件集合有变",
    "official source bytes are unchanged": "官方来源未变",
    "source bytes changed and the baseline has no content fingerprints": "来源有变（基线无内容指纹）",
    "only markup or encoding changed; visible content is identical": "只有标记或编码变化，可见内容相同",
    "visible source content changed": "来源的可见内容有变",
}
FIELDS = {
    "title": "课名", "instructors": "教员", "unit": "开讲单位", "units": "开讲单位", "quarters": "学期",
    "schedule": "时间与教室", "credits": "学分", "format": "授课形态", "language": "语言",
    "syllabusUpdated": "Syllabus 更新日", "class": "班级", "code": "科目代码",
}

HEALTH = {"ok": ("OK", "good"), "warning": ("Warning", "warning"), "critical": ("Critical", "critical")}
LEVELS = {"critical": ("Critical", "critical"), "warning": ("Warning", "warning")}

STYLE = """
:root{color-scheme:light;--page:#eef0f2;--surface:#ffffff;--raised:#f6f7f8;--ink:#0d1117;--ink-2:#4b5361;
--ink-3:#7a8290;--line:#e1e4e8;--line-2:#c9ced6;--series:#2a78d6;--series-soft:#e6eefa;--good:#14a44d;
--warning:#e9a100;--serious:#ec835a;--critical:#d93b3b;--neutral:#a3a9b3;--quiet:#dfe2e6;
--critical-soft:#fdeceb;--warning-soft:#fdf5df;--good-soft:#e5f5eb;--radius:8px}
@media (prefers-color-scheme:dark){:root{color-scheme:dark;--page:#0b0d10;--surface:#14171c;--raised:#1b1f25;
--ink:#e8eaed;--ink-2:#b2b8c2;--ink-3:#808896;--line:#252a31;--line-2:#353b44;--series:#3d8bea;
--series-soft:#162436;--neutral:#5f6672;--quiet:#262b32;--critical-soft:#341a1b;--warning-soft:#33290f;
--good-soft:#11291b}}
*{box-sizing:border-box}html{background:var(--page)}body{margin:0;color:var(--ink);
font:13px/1.5 system-ui,-apple-system,"Segoe UI","PingFang SC","Hiragino Sans","Noto Sans CJK SC",sans-serif}
a{color:inherit;text-decoration-color:var(--line-2);text-underline-offset:3px}a:hover{text-decoration-color:var(--ink-2)}
code,.mono{font:12px/1.5 ui-monospace,"SF Mono","Cascadia Mono",Consolas,monospace}
.top{position:sticky;top:0;z-index:2;background:var(--surface);border-bottom:1px solid var(--line)}
.top>div{max-width:88rem;margin:auto;padding:8px 16px;display:flex;gap:18px;align-items:center;flex-wrap:wrap}
.brand{font-weight:700;text-decoration:none;display:flex;gap:8px;align-items:center}
.top nav{display:flex;gap:2px}.top nav a{text-decoration:none;color:var(--ink-2);padding:4px 10px;border-radius:6px}
.top nav a:hover{background:var(--raised)}.top nav a[aria-current]{color:var(--ink);background:var(--raised);font-weight:600}
.top .stamp{margin-left:auto;color:var(--ink-3);font-size:12px}
main{max-width:88rem;margin:auto;padding:16px 16px 48px}h1{font-size:18px;margin:2px 0}
h2{font-size:12px;margin:22px 0 8px;color:var(--ink-3);text-transform:uppercase;letter-spacing:.04em;font-weight:600}
h2 a{float:right;text-transform:none;letter-spacing:0;font-weight:500}
h3{font-size:13px;margin:0}.sub{color:var(--ink-2);margin:0}
.muted{color:var(--ink-3)}.small{font-size:12px}.num{text-align:right;font-variant-numeric:tabular-nums}
time,.tab{font-variant-numeric:tabular-nums;white-space:nowrap}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius)}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%}
th,td{padding:7px 12px;text-align:left;vertical-align:middle;border-top:1px solid var(--line)}
thead th{border-top:0;font-size:11px;font-weight:600;color:var(--ink-3);white-space:nowrap;background:var(--raised)}
thead th:first-child{border-top-left-radius:var(--radius)}thead th:last-child{border-top-right-radius:var(--radius)}
tbody tr:hover{background:var(--raised)}
.badge{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;white-space:nowrap;
padding:0 8px 0 6px;border-radius:4px;background:var(--raised);border:1px solid var(--line)}
.badge i,.dot{width:8px;height:8px;border-radius:50%;background:var(--neutral);flex:none;display:inline-block}
.t-good i,.cell.t-good,.dot.t-good{background:var(--good)}.t-warning i,.cell.t-warning,.dot.t-warning{background:var(--warning)}
.t-serious i,.cell.t-serious{background:var(--serious)}.t-critical i,.cell.t-critical,.dot.t-critical{background:var(--critical)}
.t-running i,.cell.t-running{background:var(--series)}.t-neutral i,.cell.t-neutral{background:var(--neutral)}
.t-quiet i,.cell.t-quiet{background:var(--quiet)}
.dot.t-good{box-shadow:0 0 0 3px var(--good-soft)}.dot.t-critical{box-shadow:0 0 0 3px var(--critical-soft)}
.dot.t-warning{box-shadow:0 0 0 3px var(--warning-soft)}
.state{display:flex;gap:14px;align-items:center;padding:14px 18px;border-left:4px solid var(--good)}
.state.t-warning{border-left-color:var(--warning)}.state.t-critical{border-left-color:var(--critical)}
.state b{font-size:20px;letter-spacing:-.01em}.state .dot{width:12px;height:12px}
.state .meta{margin-left:auto;display:flex;gap:18px;color:var(--ink-2);font-size:12px;flex-wrap:wrap}
.lvl{font-size:11px;font-weight:700;padding:1px 7px;border-radius:4px;white-space:nowrap}
.lvl.t-critical{background:var(--critical-soft);color:var(--critical)}.lvl.t-warning{background:var(--warning-soft);color:var(--warning)}
.ok-line{padding:10px 14px;color:var(--ink-3)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(8.5rem,1fr));gap:8px}
.tile{padding:10px 14px}.tile b{display:block;font-size:20px;font-weight:650;font-variant-numeric:tabular-nums;
letter-spacing:-.02em}.tile span{color:var(--ink-3);font-size:11px}
.health{display:inline-flex;gap:8px;align-items:center;font-weight:600;white-space:nowrap}
.bars{display:grid;grid-template-columns:repeat(30,1fr);gap:2px;min-width:12rem}
.bars .cell{width:auto;height:20px;border-radius:2px}
.strip{display:flex;gap:3px;align-items:center}.cell{display:block;width:14px;height:14px;border-radius:3px;
background:var(--quiet)}a.cell:hover{outline:2px solid var(--ink-2);outline-offset:1px}
.cell.none{background:var(--quiet);opacity:.5}
.alert{border-radius:6px;padding:8px 10px;font-size:12px;background:var(--critical-soft);word-break:break-word}
.alert.warn{background:var(--warning-soft)}.banner{padding:10px 14px;margin-top:10px;display:flex;gap:10px;
align-items:center;flex-wrap:wrap}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 8px}.chip{font-size:12px;padding:2px 10px;
border:1px solid var(--line-2);border-radius:4px;text-decoration:none;color:var(--ink-2);background:var(--surface)}
.chip[aria-current]{background:var(--ink);color:var(--surface);border-color:var(--ink)}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:11px;color:var(--ink-3);margin:8px 0 0}
.legend span{display:inline-flex;gap:6px;align-items:center}.legend .cell{width:10px;height:10px}
.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(22rem,100%),1fr));gap:8px}
.chart{padding:10px 14px 6px}.chart svg{display:block;width:100%;height:auto;overflow:visible}
.chart .axis{fill:var(--ink-3);font-size:10px}.chart .grid{stroke:var(--line);stroke-width:1}
.chart .bar{fill:var(--series)}.chart .bar.miss{fill:var(--critical)}.chart g:hover .bar{opacity:.75}
.cal{display:grid;grid-template-columns:repeat(30,1fr);gap:3px}.cal .cell{width:auto;height:26px}
.cal-axis{display:flex;justify-content:space-between;font-size:11px;color:var(--ink-3);margin-top:4px}
.grid30{display:grid;grid-template-columns:repeat(30,minmax(10px,1fr));gap:2px;min-width:22rem}
.grid30 .cell{width:auto;height:14px;border-radius:2px}.grid30 .read{background:var(--series)}
.grid30 .changed{box-shadow:inset 0 0 0 2px var(--warning)}
.dur{height:6px;border-radius:3px;background:var(--series);min-width:2px}
.dur.bad{background:var(--critical)}details{border-top:1px solid var(--line)}details:first-child{border-top:0}
summary{cursor:pointer;padding:9px 12px;list-style-position:inside}summary:hover{background:var(--raised)}
details table{margin:0 0 8px}.k-added{color:var(--good)}.k-removed{color:var(--critical)}
pre{margin:0;padding:12px;overflow:auto;max-height:28rem;font:12px/1.45 ui-monospace,Consolas,monospace}
.kv{display:grid;grid-template-columns:repeat(auto-fill,minmax(14rem,1fr));gap:10px 20px;margin:0;padding:12px 16px}
.kv div{min-width:0}.kv dt{color:var(--ink-3);font-size:11px}.kv dd{margin:0;word-break:break-word}
.kv.rows{display:grid;grid-template-columns:max-content 1fr;gap:6px 16px}
.log{display:flex;flex-direction:column-reverse;max-height:26rem;overflow:auto;background:var(--raised);
border-top:1px solid var(--line);border-radius:0 0 var(--radius) var(--radius)}.log pre{max-height:none}
.live{display:flex;gap:10px;align-items:center;flex-wrap:wrap;padding:10px 14px}
.live a.more{margin-left:auto}
abbr{text-decoration:underline dotted var(--ink-3);cursor:help}
"""


# -- Formatting ---------------------------------------------------------------

def esc(value):
    return html.escape("" if value is None else str(value), quote=True)


def moment(value):
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed.astimezone(JST) if parsed.tzinfo else None


def when(value, pattern="%m-%d %H:%M"):
    at = moment(value)
    return at.strftime(pattern) if at else "—"


def ago(value, now):
    at = moment(value)
    if not at:
        return ""
    total = int((now - at).total_seconds())
    if total < 60:
        return f"{max(total, 0)}s ago"
    if total < 3600:
        return f"{total // 60}m ago"
    if total < 48 * 3600:
        return f"{total // 3600}h ago"
    return f"{total // 86400}d ago"


def took(record):
    start, end = moment(record.get("startedAt")), moment(record.get("finishedAt"))
    return span(int((end - start).total_seconds())) if start and end else ""


def span(total):
    if total is None:
        return "—"
    if total >= 3600:
        return f"{total // 3600} 时 {total % 3600 // 60} 分"
    return f"{total // 60} 分 {total % 60} 秒" if total >= 60 else f"{total} 秒"


def number(value):
    return f"{value:,}" if isinstance(value, int) else "—"


def compact(value):
    if not isinstance(value, (int, float)):
        return "—"
    for size, unit in ((1e6, "M"), (1e3, "k")):
        if abs(value) >= size:
            return f"{value / size:.1f}".rstrip("0").rstrip(".") + unit
    return f"{value:g}"


def badge(state):
    label, tone, meaning = STATES.get(state, (state, "neutral", ""))
    return f'<span class="badge t-{tone}" title="{esc(meaning)}"><i></i>{esc(label)}</span>'


def tone_badge(label, tone, title=""):
    return f'<span class="badge t-{tone}" title="{esc(title)}"><i></i>{esc(label)}</span>'


def run_link(record, text=None):
    return f'<a href="/runs/{esc(record["run"])}">{text or esc(when(record["startedAt"]))}</a>'


def commit_link(record):
    if record.get("commit"):
        return f'<a class="mono" href="{REPO_URL}/commit/{esc(record["commit"])}">{esc(record["commit"][:7])}</a>'
    return '<span class="muted">—</span>'


def note(record):
    text = record.get("note")
    return esc(NOTES.get(text, text)) if text else ""


def change_summary(record):
    items = record.get("changes") or []
    if not items:
        return '<span class="muted">—</span>'
    files = esc("\n".join(item["file"] for item in items))
    if any("added" in item for item in items):
        added, removed, changed = (sum(item.get(key, 0) for item in items) for key in ("added", "removed", "changed"))
        return (f'<span title="{files}">{len(items)} 个文件 · <span class="k-added">+{added}</span> '
                f'<span class="k-removed">−{removed}</span> ~{changed}</span>')
    return f'<span title="{files}">{len(items)} 个文件</span>'


def legend():
    shown = ("published", "unchanged", "checked", "retry", "interrupted", "failed", "running")
    return '<p class="legend">' + "".join(
        f'<span><i class="cell t-{STATES[state][1]}"></i>{esc(STATES[state][0])}</span>' for state in shown) + "</p>"


def next_run(plan, last=None):
    if not plan:
        return '<span class="muted">手动运行</span>'
    if plan.get("paused"):
        return tone_badge(f"暂停：{plan['paused']}", "warning")
    if last and last["status"] == "running":
        return '<span class="muted">本次运行中</span>'
    return "即将运行" if plan.get("due") else f'<time>{esc(when(plan["next"]))}</time>'


def health_mark(level, label=None):
    text, tone = HEALTH[level]
    return f'<span class="health"><i class="dot t-{tone}"></i>{esc(label or text)}</span>'


def layout(title, body, *, current="", refresh=60, stamp=""):
    nav = "".join(f'<a href="{href}"{" aria-current=page" if key == current else ""}>{label}</a>'
                  for key, href, label in (("overview", "/", "Overview"), ("runs", "/runs", "Runs"),
                                           ("courses", "/courses", "课程轮转"), ("api", "/api/status", "JSON")))
    return f"""<!doctype html><html lang="zh-Hans"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="{refresh}">
<title>{esc(title)} · Isct-Data</title><style>{STYLE}</style></head><body>
<div class="top"><div><a class="brand" href="/">Isct-Data</a><nav>{nav}</nav>
<span class="stamp">{esc(stamp) + " JST · " if stamp else ""}auto-refresh {refresh}s</span></div></div>
<main>{body}</main></body></html>""".encode()


def runs_table(found, *, show_job=True):
    if not found:
        return '<p class="muted" style="padding:12px 16px;margin:0">暂无记录</p>'
    head = (("<th>开始</th>" + ("<th>任务</th>" if show_job else "") + "<th>结果</th><th>触发</th><th>用时</th>"
             '<th class="num">请求</th><th class="num">tokens</th><th>变化</th><th>提交</th>'))
    rows = "".join(
        f'<tr><td>{run_link(record)}</td>' + (f'<td>{esc(JOBS[record["job"]])}</td>' if show_job else "")
        + f'<td>{badge(record["status"])}</td>'
        f'<td class="muted">{"定时" if record.get("trigger") == "schedule" else "手动" if record.get("trigger") else "—"}</td>'
        f'<td class="tab">{took(record) or "—"}</td><td class="num">{number(record.get("requests"))}</td>'
        f'<td class="num">{compact(record.get("tokens")) if record.get("tokens") else "—"}</td>'
        f'<td>{change_summary(record)}</td><td>{commit_link(record)}</td></tr>' for record in found)
    return f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div>'


def bar_chart(series, key, title, fmt=compact, scale=1):
    """One measure per run as thin bars on one axis; each bar's tooltip carries its value."""
    values = [(point, point.get(key)) for point in series]
    if not any(isinstance(value, (int, float)) and value for _, value in values):
        return f'<div class="panel chart"><h3>{esc(title)}</h3><p class="muted small">没有数据</p></div>'
    top = max(value / scale for _, value in values if isinstance(value, (int, float))) or 1
    width, height, left, base = 600, 150, 40, 130
    step = (width - left) / max(len(values), 1)
    bar = max(2.0, min(18.0, step - 2))
    marks = []
    for index, (point, value) in enumerate(values):
        x = left + index * step + (step - bar) / 2
        label = f'{when(point["at"])} · {STATES[point["status"]][0]} · {fmt(value / scale) if value is not None else "—"}'
        if not isinstance(value, (int, float)):
            marks.append(f'<g><title>{esc(label)}</title><rect x="{x:.1f}" y="{base - 2}" width="{bar:.1f}" height="2" '
                         f'fill="var(--quiet)"/></g>')
            continue
        h = max(2.0, (value / scale) / top * (base - 14))
        y, r = base - h, min(4.0, bar / 2, h)
        path = (f"M{x:.1f},{base} V{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} H{x + bar - r:.1f} "
                f"Q{x + bar:.1f},{y:.1f} {x + bar:.1f},{y + r:.1f} V{base} Z")
        miss = " miss" if point["status"] in FAILED else ""
        marks.append(f'<a href="/runs/{esc(point["run"])}"><g><title>{esc(label)}</title>'
                     f'<rect x="{x - 1:.1f}" y="0" width="{bar + 2:.1f}" height="{base}" fill="transparent"/>'
                     f'<path class="bar{miss}" d="{path}"/></g></a>')
    first, last = when(series[0]["at"], "%m-%d"), when(series[-1]["at"], "%m-%d")
    return f"""<div class="panel chart"><h3>{esc(title)}</h3>
<svg viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}">
<line class="grid" x1="{left}" x2="{width}" y1="{base - (base - 14)}" y2="{base - (base - 14)}"/>
<text class="axis" x="{left - 6}" y="{base - (base - 14) + 3}" text-anchor="end">{esc(fmt(top))}</text>
<line class="grid" x1="{left}" x2="{width}" y1="{base}" y2="{base}"/>
<text class="axis" x="{left - 6}" y="{base + 3}" text-anchor="end">0</text>
{"".join(marks)}
<text class="axis" x="{left}" y="{height - 2}">{esc(first)}</text>
<text class="axis" x="{width}" y="{height - 2}" text-anchor="end">{esc(last)}</text></svg></div>"""


# -- Pages --------------------------------------------------------------------

def day_bars(calendar):
    """One cell per day, coloured by that day's last run, like an uptime bar."""
    cells = "".join(
        f'<a class="cell t-{STATES[day["record"]["status"]][1]}" href="/runs/{esc(day["record"]["run"])}" '
        f'title="{esc(day["day"])} · {esc(STATES[day["record"]["status"]][0])}"></a>' if day["record"]
        else f'<span class="cell none" title="{esc(day["day"])} · 无运行"></span>' for day in calendar)
    return f'<div class="bars">{cells}</div>'


def freshness(row, now):
    success = row["lastSuccess"]
    if not success:
        return '<span class="muted">never</span>'
    return (f'<time title="{esc(when(success["startedAt"], "%Y-%m-%d %H:%M"))}">'
            f'{esc(ago(success.get("finishedAt") or success["startedAt"], now))}</time>')


def job_row(row, now):
    last, plan = row["last"], row["plan"]
    done, total = row["success"]
    state = health_mark(row["health"]) if row["scheduled"] else '<span class="muted">手动</span>'
    latest = (f'{badge(last["status"])} <span class="muted">{run_link(last, esc(ago(last["startedAt"], now)))}</span>'
              if last else '<span class="muted">暂无记录</span>')
    return (f'<tr><td>{state}</td><td><a href="/jobs/{esc(row["job"])}"><b>{esc(JOBS[row["job"]])}</b></a></td>'
            f'<td class="tab">{freshness(row, now)}</td><td>{latest}</td>'
            f'<td class="tab">{next_run(plan, last) if row["scheduled"] else "—"}</td>'
            f'<td style="width:28%">{day_bars(row["calendar"])}</td>'
            f'<td class="num">{f"{done}/{total}" if total else "—"}</td></tr>')


def alert_rows(raised, now):
    if not raised:
        return '<div class="panel ok-line">No alerts.</div>'
    rows = []
    for item in raised:
        detail = f'<div class="muted small">{esc(item["detail"])}</div>' if item["detail"] else ""
        link = f'<a href="/runs/{esc(item["run"])}">Details</a>' if item["run"] else ""
        tag, tone = LEVELS[item["level"]]
        rows.append(f'<tr><td><span class="lvl t-{tone}">{tag}</span></td>'
                    f'<td>{esc(JOBS[item["job"]] if item["job"] else "Scheduler")}</td>'
                    f'<td><b>{esc(item["title"])}</b>{detail}</td>'
                    f'<td class="tab muted">{esc(ago(item["since"], now))}</td><td>{link}</td></tr>')
    return ('<div class="panel scroll"><table><thead><tr><th>Level</th><th>Target</th><th>Issue</th><th>Since</th><th></th>'
            f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>')


def live_run(record, now, compact_log=False):
    """A running run: which step it is on and the end of its log, newest line at the bottom."""
    steps = record.get("steps") or []
    current = f'<span class="muted">after step {len(steps)}: <code>{esc(steps[-1]["command"])}</code></span>' if steps else ""
    lines = record.get("logTail") or []
    log = (f'<div class="log"><pre>{esc(chr(10).join(lines[-12:] if compact_log else lines))}</pre></div>'
           if lines else '<p class="muted small" style="padding:0 14px 10px;margin:0">No log output yet.</p>')
    return (f'<div class="panel" style="margin-bottom:8px"><div class="live">{badge("running")} '
            f'<a href="/runs/{esc(record["run"])}"><b>{esc(JOBS[record["job"]])}</b></a>'
            f'<span class="muted">started {esc(ago(record["startedAt"], now))}</span>{current}'
            f'<a class="more" href="/runs/{esc(record["run"])}/log">Raw log</a></div>{log}</div>')


def overview(view):
    now = moment(view["generatedAt"])
    raised, level = view["alerts"], view["health"]
    critical = sum(item["level"] == "critical" for item in raised)
    warnings = len(raised) - critical
    headline = " · ".join(part for part in (f"{critical} Critical" if critical else "",
                                            f"{warnings} Warning{'s' if warnings > 1 else ''}" if warnings else "")
                          if part) or "All OK"
    beat = view["heartbeat"]
    meta = f'<span>Heartbeat <b>{esc(ago(beat, now)) if beat else "none"}</b></span>'
    state = (f'<div class="panel state t-{HEALTH[level][1]}"><i class="dot t-{HEALTH[level][1]}"></i><b>{esc(headline)}</b>'
             f'<div class="meta">{meta}</div></div>')
    live = "".join(live_run(record, now, compact_log=True) for record in view["running"])
    week = view["week"]
    tiles = "".join(f'<div class="panel tile"><b>{value}</b><span>{label}</span></div>' for value, label in (
        (week["runs"], "Runs"), (week["published"], "Published to main"), (week["failed"], "Not OK"),
        (compact(week["requests"]), "Source requests"), (compact(week["tokens"]), "Model tokens")))
    rows = "".join(job_row(row, now) for row in view["jobs"] if row["scheduled"] or row["last"])
    jobs = ('<div class="panel scroll"><table><thead><tr><th>Status</th><th>Job</th>'
            '<th><abbr title="最近一次成功运行（已发布、无变化或已检查）的时间：数据最多旧到这里">Last success</abbr></th>'
            '<th>Last run</th><th>Next run</th><th>Last 30 days</th><th class="num">30d OK</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>')
    body = f"""{state}
{f'<h2>Running</h2>{live}' if live else ""}
<h2>Alerts</h2>{alert_rows(raised, now)}
<h2>Jobs</h2>{jobs}{legend()}
<h2>Last 7 days</h2><div class="tiles">{tiles}</div>
<h2>Recent runs <a href="/runs">All runs →</a></h2><div class="panel">{runs_table(view["recent"])}</div>"""
    return layout("Overview", body, current="overview", refresh=30, stamp=when(view["generatedAt"]))


def runs(view):
    chosen = view["filter"]

    def chip(label, **change):
        params = {key: value for key, value in {**chosen, **change}.items() if value}
        selected = all(chosen.get(key) == value for key, value in change.items())
        return (f'<a class="chip" href="/runs?{esc(urlencode(params))}"{" aria-current=true" if selected else ""}>'
                f'{esc(label)}</a>')

    jobs = chip("All jobs", job=None) + "".join(chip(JOBS[job], job=job) for job in view["jobs"])
    states = chip("All results", status=None) + "".join(
        chip(STATES[state][0], status=state) for state in ("published", "unchanged", "checked", "retry", "failed",
                                                           "interrupted", "running"))
    shown = len(view["runs"])
    body = (f'<h1>Runs</h1><p class="sub muted">{view["matching"]} runs'
            f'{f", showing the latest {shown}" if view["matching"] > shown else ""} · records are kept for 180 days</p>'
            f'<div style="margin-top:12px" class="chips">{jobs}</div><div class="chips">{states}</div>'
            f'<div class="panel">{runs_table(view["runs"])}</div>')
    return layout("Runs", body, current="runs", stamp=when(view["generatedAt"]))


def history(view, now):
    job = view["job"]
    runs = view["runs"]
    cells = "".join(
        f'<a class="cell t-{STATES[day["record"]["status"]][1]}" href="/runs/{esc(day["record"]["run"])}" '
        f'title="{esc(day["day"])} · {esc(STATES[day["record"]["status"]][0])}"></a>' if day["record"]
        else f'<span class="cell none" title="{esc(day["day"])} · 无运行"></span>' for day in view["calendar"])
    done = [record for record in runs if record["status"] != "running"]
    ok = sum(record["status"] in ("published", "unchanged", "checked", "ok") for record in done)
    durations = [point["seconds"] for point in view["series"] if point["seconds"] is not None]
    tokens = sum(record.get("tokens") or 0 for record in runs)
    tiles = "".join(f'<div class="panel tile"><b>{value}</b><span>{label}</span></div>' for value, label in (
        (len(runs), f"{view['days']} 天内运行"), (f"{ok}/{len(done)}" if done else "—", "成功"),
        (sum(record["status"] == "published" for record in runs), "发布到 main"),
        (span(sum(durations) // len(durations)) if durations else "—", "平均用时"),
        (compact(tokens) if tokens else "—", "模型 tokens")))
    in_minutes = max(durations, default=0) >= 120
    charts = [bar_chart(view["series"], "seconds", "每次用时（分钟）" if in_minutes else "每次用时（秒）",
                        lambda value: f"{value:.1f}".rstrip("0").rstrip("."), 60 if in_minutes else 1),
              bar_chart(view["series"], "requests", "每次来源请求数")]
    if tokens:
        charts.append(bar_chart(view["series"], "tokens", "每次模型 tokens"))
    first = view["calendar"][0]["day"][5:]
    live = "".join(live_run(record, now, compact_log=True) for record in view.get("running") or [])
    body = f"""<p class="sub"><a href="/">Overview</a> / Job</p><h1>{esc(JOBS[job])}</h1>
<p class="sub">Next run: {next_run(view["plan"], runs[0] if runs else None)}</p>
{f'<h2>Running</h2>{live}' if live else ""}
{f'<h2>Alerts</h2>{alert_rows(view["alerts"], now)}' if view.get("alerts") else ""}
<h2>Last {view["days"]} days</h2><div class="tiles">{tiles}</div>
<h2>Daily result <span class="muted small">每天最后一次</span></h2><div class="panel" style="padding:14px 16px">
<div class="cal">{cells}</div><div class="cal-axis"><span>{esc(first)}</span><span>today</span></div>{legend()}</div>
<h2>每次运行</h2><div class="charts">{"".join(charts)}</div>
<p class="muted small">红色柱为未成功的运行。点击柱子进入该次运行。</p>
<h2>Runs</h2><div class="panel">{runs_table(runs, show_job=False)}</div>"""
    return layout(JOBS[job], body, refresh=15 if live else 60, stamp=when(now.isoformat()))


def step_outcome(step):
    if step["exit"] == 0:
        return ""
    if step["exit"] is None:
        return tone_badge("出错" if step.get("phase") else "超时或异常", "critical")
    return tone_badge(f"退出码 {step['exit']}", "critical")


def steps_table(record):
    steps = record.get("steps") or []
    if not steps:
        return '<p class="muted" style="padding:12px 16px;margin:0">没有记录命令步骤（旧版运行记录）</p>'
    longest = max(step["seconds"] for step in steps) or 1
    start = moment(record["startedAt"])
    rows = "".join(
        f'<tr><td class="tab muted">+{span(int((moment(step["startedAt"]) - start).total_seconds()))}</td>'
        f'<td class="tab num">{span(int(step["seconds"]))}</td>'
        f'<td style="width:22%"><div class="dur{"" if step["exit"] == 0 else " bad"}" '
        f'style="width:{max(1.0, step["seconds"] / longest * 100):.1f}%"></div></td>'
        f'<td>{step_outcome(step)} '
        f'{f"<b>{esc(step["command"])}</b>" if step.get("phase") else f"<code>{esc(step["command"])}</code>"}'
        f'</td></tr>' for step in steps)
    return (f'<div class="scroll"><table><thead><tr><th>开始于</th><th class="num">用时</th><th>占比</th><th>命令</th>'
            f'</tr></thead><tbody>{rows}</tbody></table></div>')


def sources_table(record):
    rows = record.get("sources") or []
    counts = {}
    for row in rows:
        counts[row["change"]] = counts.get(row["change"], 0) + 1
    summary = " ".join(tone_badge(f"{SOURCE_CHANGES[kind][0]} {count}", SOURCE_CHANGES[kind][1])
                       for kind, count in counts.items())
    ordered = sorted(rows, key=lambda row: (row["change"] == "same", row["url"]))
    body = "".join(f'<tr><td>{tone_badge(*SOURCE_CHANGES[row["change"]])}</td>'
                   f'<td><a class="mono" href="{esc(row["url"])}">{esc(row["url"])}</a></td></tr>' for row in ordered)
    return (f'<div style="padding:10px 12px 0">{summary}</div><div class="scroll"><table><thead><tr><th>变化</th>'
            f'<th>来源</th></tr></thead><tbody>{body}</tbody></table></div>')


def course_items(change):
    items = change.get("items") or []
    rows = "".join(
        f'<tr><td class="k-{item["kind"]}">{ {"added": "新增", "removed": "删除", "changed": "修改"}[item["kind"]] }</td>'
        f'<td class="mono">{esc(item.get("code"))}</td><td>{esc(item.get("title"))}</td>'
        f'<td class="muted">{esc("、".join(FIELDS.get(field, field) for field in item.get("fields", [])))}</td>'
        f'<td class="mono muted">{esc(item["id"])}</td></tr>' for item in items)
    more = change["added"] + change["removed"] + change["changed"] - len(items)
    return (f'<details><summary><code>{esc(change["file"])}</code> · <span class="k-added">+{change["added"]}</span> '
            f'<span class="k-removed">−{change["removed"]}</span> ~{change["changed"]}</summary>'
            f'<div class="scroll"><table><thead><tr><th>变化</th><th>代码</th><th>课名</th><th>改动的字段</th>'
            f'<th>ID</th></tr></thead><tbody>{rows}</tbody></table></div>'
            + (f'<p class="muted small" style="padding:0 12px">另有 {more} 项未列出</p>' if more > 0 else "") + "</details>")


def detail(view):
    record = view["record"]
    run = record["run"]
    facts = [("任务", f'<a href="/jobs/{esc(record["job"])}">{esc(JOBS[record["job"]])}</a>'),
             ("结果", badge(record["status"]) + (f' <span class="muted">{note(record)}</span>' if record.get("note") else "")),
             ("开始", f'<time>{esc(when(record["startedAt"], "%Y-%m-%d %H:%M:%S"))}</time>'),
             ("用时", took(record) or "进行中"),
             ("触发", {"schedule": "定时", "manual": "手动"}.get(record.get("trigger"), "—")),
             ("运行时的 main", f'<a class="mono" href="{REPO_URL}/commit/{esc(record["base"])}">{esc(record["base"][:7])}</a>'
              if record.get("base") else "—"),
             ("发布的提交", commit_link(record)),
             ("请求数", number(record.get("requests"))),
             ("模型 tokens", number(record.get("tokens")) if record.get("tokens") else "—"),
             ("运行 ID", f'<code>{esc(run)}</code>')]
    kv = "".join(f"<div><dt>{label}</dt><dd>{value}</dd></div>" for label, value in facts)
    sections = []
    if record["status"] == "running":
        sections.append(f'<h2>Log <span class="muted small">live · refreshes every 5s</span></h2>{live_run(record, moment(view["generatedAt"]))}')
    if record.get("error"):
        tail = "\n".join(view["logTail"])
        sections.append(f'<h2>错误</h2><div class="alert{" warn" if record["status"] == "retry" else ""}">'
                        f'{esc(record["error"])}</div>'
                        + (f'<div class="panel" style="margin-top:10px"><pre>{esc(tail)}</pre></div>' if tail else ""))
    sections.append(f'<h2>步骤 <span class="muted small">{len(record.get("steps") or [])} 步</span></h2>'
                    f'<div class="panel">{steps_table(record)}</div>')
    if record.get("sources"):
        sections.append(f'<h2>来源 <span class="muted small">与已审核的基线比较</span></h2>'
                        f'<div class="panel">{sources_table(record)}</div>')
    if record.get("review") or record.get("authorErrors"):
        review = record.get("review") or {}
        rows = [("完成的作者", "、".join(review.get("authors") or []) or "无"),
                ("两份结果", "一致" if review.get("same") else f'不一致，{review.get("differences", 0)} 处差异'),
                ("仲裁", "已由 Sol 仲裁" if review.get("arbitrated") else "不需要")]
        rows += [(f"作者 {slot.upper()} 出错", esc(error)) for slot, error in (record.get("authorErrors") or {}).items()]
        sections.append('<h2>审核比对</h2><div class="panel"><dl class="kv rows">'
                        + "".join(f"<dt>{label}</dt><dd>{value}</dd>" for label, value in rows) + "</dl></div>")
    if record.get("modelCalls"):
        calls = record["modelCalls"]
        rows = "".join(f'<tr><td>{esc(call.get("label") or "—")}</td><td class="mono">{esc(call["model"])}</td>'
                       f'<td class="num">{number(call["input"])}</td><td class="num">{number(call["cached"])}</td>'
                       f'<td class="num">{number(call["output"])}</td></tr>' for call in calls)
        sections.append(f'<h2>模型调用 <span class="muted small">{len(calls)} 次响应</span></h2><div class="panel scroll">'
                        f'<table><thead><tr><th>用途</th><th>模型</th><th class="num">输入</th><th class="num">缓存输入</th>'
                        f'<th class="num">输出</th></tr></thead><tbody>{rows}</tbody></table></div>')
    if record.get("years"):
        rows = "".join(f'<tr><td>{esc(year["year"])}</td><td>{esc(year.get("skipped") or "")}'
                       f'{number(year.get("offerings")) + " 门课，" + str(year.get("files")) + " 个文件" if "offerings" in year else ""}</td>'
                       f'<td>{"、".join(f"<code>{esc(name)}</code>" for name in year.get("readInFull") or []) or "—"}</td></tr>'
                       for year in record["years"])
        sections.append('<h2>Syllabus 读取</h2><div class="panel scroll"><table><thead><tr><th>学年</th><th>内容</th>'
                        f'<th>重读详情页的文件</th></tr></thead><tbody>{rows}</tbody></table></div>')
    if record.get("changes"):
        if any("items" in change for change in record["changes"]):
            body = "".join(course_items(change) for change in record["changes"])
        else:
            body = "<ul>" + "".join(f'<li><code>{esc(change["file"])}</code></li>' for change in record["changes"]) + "</ul>"
        sections.append(f'<h2>变化</h2><div class="panel">{body}</div>')
    def artifact(item):
        if item["text"]:
            return f'<a class="mono" href="/runs/{esc(run)}/files/{esc(item["path"])}">{esc(item["path"])}</a>'
        return f'<code>{esc(item["path"])}</code>'

    files = "".join(f'<tr><td>{artifact(item)}</td><td class="num">{compact(item["bytes"])}B</td></tr>'
                    for item in view["files"])
    log_link = f'<a href="/runs/{esc(run)}/log">Raw log</a>' if view["hasLog"] else '<span class="muted">日志已过保留期</span>'
    sections.append(f'<h2>记录与文件</h2><div class="panel scroll"><table><thead><tr><th>{log_link} · '
                    f'<a href="/runs/{esc(run)}/files/status.json">status.json</a></th><th class="num">大小</th></tr></thead>'
                    f'<tbody>{files or "<tr><td class=muted>没有其他文件（产物保留 7 天）</td><td></td></tr>"}</tbody></table></div>')
    body = (f'<p class="sub"><a href="/">Overview</a> / <a href="/jobs/{esc(record["job"])}">{esc(JOBS[record["job"]])}</a> / 运行</p>'
            f'<h1>{esc(JOBS[record["job"]])} · {esc(when(record["startedAt"]))}</h1>'
            f'<div class="panel" style="margin-top:14px"><dl class="kv">{kv}</dl></div>' + "".join(sections))
    return layout("Run", body, refresh=5 if record["status"] == "running" else 300)


def courses(view):
    summary = view["summary"]
    days = view["days"]
    tiles = "".join(f'<div class="panel tile"><b>{value}</b><span>{label}</span></div>' for value, label in (
        (summary["files"], "课程文件"), (number(summary["offerings"]), "开讲科目"),
        (f'{summary["covered"]}/{summary["files"]}', f"{len(days)} 天内重读过详情页"),
        (esc(summary["oldest"] or "—"), "最久没重读的日期"), (summary["unverified"], "还没重读过")))
    rows = []
    for row in view["files"]:
        reads, changed = set(row["reads"]), set(row["changed"])
        cells = "".join(
            f'<span class="cell{" read" if day in reads else ""}{" changed" if day in changed else ""}" '
            f'title="{esc(day)}{" · 重读了详情页" if day in reads else ""}{" · 有变化" if day in changed else ""}"></span>'
            for day in days)
        rows.append(f'<tr><td>{esc(row.get("name") or "")}<div class="muted small mono">{esc(row["file"])}</div></td>'
                    f'<td class="num">{number(row["offerings"])}</td>'
                    f'<td class="tab">{esc(row["verified"] or "还没重读过")}</td><td><div class="grid30">{cells}</div></td></tr>')
    grid = (f'<div class="scroll"><table><thead><tr><th>文件（越靠前越早轮到）</th>'
            f'<th class="num">科目</th><th><abbr title="上次读这个文件的英文列表和每门课的详情页的日期">上次重读详情页</abbr></th><th>{esc(days[0][5:])} → {esc(days[-1][5:])}</th></tr></thead>'
            f'<tbody>{"".join(rows) or "<tr><td colspan=4 class=muted>还没有运行过 Syllabus 抓取</td></tr>"}</tbody></table></div>')
    key = ('<p class="legend"><span><i class="cell" style="background:var(--series)"></i>这天重读了详情页</span>'
           '<span><i class="cell" style="box-shadow:inset 0 0 0 2px var(--warning)"></i>这天有变化</span>'
           '<span><i class="cell"></i>只读了日文列表</span></p>')
    changes = "".join(
        f'<div class="panel" style="margin-bottom:10px"><div style="padding:10px 12px;display:flex;gap:10px;'
        f'align-items:center;flex-wrap:wrap">{run_link(record)} {badge(record["status"])} {change_summary(record)} '
        f'{commit_link(record)}</div>' + "".join(course_items(change) for change in record["changes"]) + "</div>"
        for record in view["changes"]) or '<p class="muted">最近没有课程变化</p>'
    body = f"""<h1>课程文件轮转</h1><p class="sub">每天都读一遍日文列表，能看到课程的增删和列表上的字段。时间教室、学分等只在详情页上，英文课名只在英文列表上，所以每天轮流重读约 1/30 的文件的英文列表和详情页，30 天轮完一圈。</p>
<div class="tiles">{tiles}</div><h2>各文件</h2><div class="panel">{grid}</div>{key}
<h2>最近的课程变化</h2>{changes}"""
    return layout("课程轮转", body, current="courses")
