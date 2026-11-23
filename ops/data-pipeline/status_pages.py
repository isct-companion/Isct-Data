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

STYLE = """
:root{color-scheme:light;--page:#f4f4f2;--surface:#fcfcfb;--raised:#ffffff;--ink:#0b0b0b;--ink-2:#52514e;
--ink-3:#77766f;--line:#e2e1dc;--line-2:#cfcec7;--series:#2a78d6;--series-soft:#e6eefa;--good:#0ca30c;
--warning:#fab219;--serious:#ec835a;--critical:#d03b3b;--neutral:#a9a8a0;--quiet:#d9d8d2;
--critical-soft:#fbeceb;--warning-soft:#fdf4de;--radius:12px}
@media (prefers-color-scheme:dark){:root{color-scheme:dark;--page:#121211;--surface:#1a1a19;--raised:#21211f;
--ink:#f0efec;--ink-2:#c3c2b7;--ink-3:#9a998f;--line:#2e2e2b;--line-2:#3d3d39;--series:#3987e5;
--series-soft:#1b2a3d;--neutral:#77766f;--quiet:#383835;--critical-soft:#3a1f1e;--warning-soft:#382d14}}
*{box-sizing:border-box}html{background:var(--page)}body{margin:0;color:var(--ink);
font:14px/1.5 system-ui,-apple-system,"Segoe UI","PingFang SC","Hiragino Sans","Noto Sans CJK SC",sans-serif}
a{color:inherit;text-decoration-color:var(--line-2);text-underline-offset:3px}a:hover{text-decoration-color:var(--ink-2)}
code,.mono{font:12px/1.5 ui-monospace,"SF Mono","Cascadia Mono",Consolas,monospace}
.top{position:sticky;top:0;z-index:2;background:color-mix(in srgb,var(--page) 88%,transparent);
backdrop-filter:blur(8px);border-bottom:1px solid var(--line)}
.top div{max-width:84rem;margin:auto;padding:10px 16px;display:flex;gap:20px;align-items:center;flex-wrap:wrap}
.brand{font-weight:700;text-decoration:none}.top nav{display:flex;gap:14px;color:var(--ink-2)}
.top nav a{text-decoration:none}.top nav a[aria-current]{color:var(--ink);font-weight:600}
.top .stamp{margin-left:auto;color:var(--ink-3);font-size:12px}
main{max-width:84rem;margin:auto;padding:20px 16px 56px}h1{font-size:22px;margin:4px 0 2px;letter-spacing:-.01em}
h2{font-size:15px;margin:32px 0 10px}h3{font-size:14px;margin:0}.sub{color:var(--ink-2);margin:0}
.muted{color:var(--ink-3)}.small{font-size:12px}.num{text-align:right;font-variant-numeric:tabular-nums}
time,.tab{font-variant-numeric:tabular-nums;white-space:nowrap}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius)}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%}
th,td{padding:8px 12px;text-align:left;vertical-align:top;border-top:1px solid var(--line)}
thead th{border-top:0;font-size:12px;font-weight:600;color:var(--ink-3);white-space:nowrap}
tbody tr:hover{background:color-mix(in srgb,var(--series-soft) 40%,transparent)}
.badge{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;white-space:nowrap;
padding:1px 9px 1px 7px;border:1px solid var(--line-2);border-radius:999px;background:var(--raised)}
.badge i{width:8px;height:8px;border-radius:50%;background:var(--neutral)}
.t-good i,.cell.t-good{background:var(--good)}.t-warning i,.cell.t-warning{background:var(--warning)}
.t-serious i,.cell.t-serious{background:var(--serious)}.t-critical i,.cell.t-critical{background:var(--critical)}
.t-running i,.cell.t-running{background:var(--series)}.t-neutral i,.cell.t-neutral{background:var(--neutral)}
.t-quiet i,.cell.t-quiet{background:var(--quiet)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(9.5rem,1fr));gap:10px;margin-top:16px}
.tile{padding:12px 14px}.tile b{display:block;font-size:22px;font-weight:650;font-variant-numeric:tabular-nums;
letter-spacing:-.02em}.tile span{color:var(--ink-2);font-size:12px}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(24rem,100%),1fr));gap:12px}
.card{padding:14px 16px;display:flex;flex-direction:column;gap:10px}
.card header{display:flex;justify-content:space-between;align-items:flex-start;gap:10px}
.card header a{text-decoration:none}.card header a:hover h3{text-decoration:underline}
.facts{display:grid;grid-template-columns:auto 1fr;gap:2px 12px;margin:0;font-size:13px}
.facts dt{color:var(--ink-3)}.facts dd{margin:0}
.metrics{display:flex;gap:18px;font-size:12px;color:var(--ink-2)}.metrics b{display:block;font-size:15px;
color:var(--ink);font-variant-numeric:tabular-nums}
.strip{display:flex;gap:3px;align-items:center}.cell{display:block;width:14px;height:14px;border-radius:3px;
background:var(--quiet)}.strip a.cell:hover{outline:2px solid var(--ink-2);outline-offset:1px}
.cell.none{background:transparent;border:1px dashed var(--line-2)}
.alert{border-radius:8px;padding:8px 10px;font-size:12px;background:var(--critical-soft);word-break:break-word}
.alert.warn{background:var(--warning-soft)}.banner{padding:10px 14px;margin-top:14px;display:flex;gap:10px;
align-items:center;flex-wrap:wrap}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 10px}.chip{font-size:12px;padding:2px 10px;
border:1px solid var(--line-2);border-radius:999px;text-decoration:none;color:var(--ink-2);background:var(--surface)}
.chip[aria-current]{background:var(--ink);color:var(--surface);border-color:var(--ink)}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--ink-2);margin:8px 0 0}
.legend span{display:inline-flex;gap:6px;align-items:center}.legend .cell{width:10px;height:10px}
.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(22rem,100%),1fr));gap:12px}
.chart{padding:12px 14px 8px}.chart svg{display:block;width:100%;height:auto;overflow:visible}
.chart .axis{fill:var(--ink-3);font-size:10px}.chart .grid{stroke:var(--line);stroke-width:1}
.chart .bar{fill:var(--series)}.chart .bar.miss{fill:var(--critical)}.chart g:hover .bar{opacity:.75}
.cal{display:grid;grid-template-columns:repeat(30,1fr);gap:3px}.cal .cell{width:auto;aspect-ratio:1;height:auto}
.cal-axis{display:flex;justify-content:space-between;font-size:11px;color:var(--ink-3);margin-top:4px}
.grid30{display:grid;grid-template-columns:repeat(30,minmax(10px,1fr));gap:2px;min-width:22rem}
.grid30 .cell{width:auto;height:14px;border-radius:2px}.grid30 .read{background:var(--series)}
.grid30 .changed{box-shadow:inset 0 0 0 2px var(--warning)}
.dur{height:6px;border-radius:3px;background:var(--series);min-width:2px}
.dur.bad{background:var(--critical)}details{border-top:1px solid var(--line)}details:first-child{border-top:0}
summary{cursor:pointer;padding:9px 12px;list-style-position:inside}summary:hover{background:var(--series-soft)}
details table{margin:0 0 8px}.k-added{color:var(--good)}.k-removed{color:var(--critical)}
pre{margin:0;padding:12px;overflow:auto;max-height:28rem;font:12px/1.45 ui-monospace,Consolas,monospace}
.split{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(26rem,100%),1fr));gap:12px}
.kv{display:grid;grid-template-columns:max-content 1fr;gap:6px 16px;margin:0;padding:14px 16px}
.kv dt{color:var(--ink-3)}.kv dd{margin:0;word-break:break-word}
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
    minutes = int((now - at).total_seconds() // 60)
    if minutes < 1:
        return "刚刚"
    if minutes < 60:
        return f"{minutes} 分钟前"
    if minutes < 48 * 60:
        return f"{minutes // 60} 小时前"
    return f"{minutes // 1440} 天前"


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


def strip(found, limit=14):
    cells = [f'<a class="cell t-{STATES[record["status"]][1]}" href="/runs/{esc(record["run"])}" '
             f'title="{esc(when(record["startedAt"]))} · {esc(STATES[record["status"]][0])}"></a>'
             for record in reversed(found[:limit])]
    cells = ['<span class="cell none" title="无记录"></span>'] * (limit - len(cells)) + cells
    return f'<div class="strip" aria-label="最近 {limit} 次运行">{"".join(cells)}</div>'


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


def layout(title, body, *, current="", refresh=60, stamp=""):
    nav = "".join(f'<a href="{href}"{" aria-current=page" if key == current else ""}>{label}</a>'
                  for key, href, label in (("overview", "/", "概览"), ("courses", "/courses", "课程轮转"),
                                           ("api", "/api/status", "JSON")))
    return f"""<!doctype html><html lang="zh-Hans"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="{refresh}">
<title>{esc(title)} · Isct-Data 数据服务</title><style>{STYLE}</style></head><body>
<div class="top"><div><a class="brand" href="/">Isct-Data 数据服务</a><nav>{nav}</nav>
<span class="stamp">日本时间 · 每 {refresh} 秒刷新{" · " + esc(stamp) if stamp else ""}</span></div></div>
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

def card(item, now):
    last, failure, plan = item["last"], item["lastFailure"], item["plan"]
    name = esc(JOBS[item["job"]])
    head = (f'<header><a href="/jobs/{esc(item["job"])}"><h3>{name}</h3></a>'
            f'{badge(last["status"]) if last else tone_badge("暂无记录", "quiet")}</header>')
    if not last:
        return (f'<article class="panel card">{head}<dl class="facts"><dt>下次</dt><dd>{next_run(plan)}</dd></dl>'
                f'{strip([])}</article>')
    facts = (f'<dl class="facts"><dt>最近</dt><dd>{run_link(last)} <span class="muted">{esc(ago(last["startedAt"], now))}'
             f'{" · " + took(last) if took(last) else ""}</span></dd>'
             + (f'<dt>说明</dt><dd>{note(last)}</dd>' if last.get("note") else "")
             + f'<dt>下次</dt><dd>{next_run(plan, last)}</dd>'
             + (f'<dt>提交</dt><dd>{commit_link(last)}</dd>' if last.get("commit") else "") + "</dl>")
    metrics = (f'<div class="metrics"><div><b>{number(last.get("requests"))}</b>请求</div>'
               f'<div><b>{change_summary(last)}</b>变化</div>'
               + (f'<div><b>{compact(last.get("tokens"))}</b>tokens</div>' if last.get("tokens") else "") + "</div>")
    alert = ""
    if failure and now - moment(failure["startedAt"]) <= timedelta(days=7):
        tone = "alert warn" if failure["status"] == "retry" else "alert"
        alert = (f'<div class="{tone}">{badge(failure["status"])} {run_link(failure)} '
                 f'{esc((failure.get("error") or "")[:240])}</div>')
    return f'<article class="panel card">{head}{facts}{metrics}{strip(item["recent"])}{alert}</article>'


def overview(view):
    now = moment(view["generatedAt"])
    week = view["week"]
    running = "".join(f'<div class="panel banner">{badge("running")} <b>{esc(JOBS[record["job"]])}</b>'
                      f'<span class="muted">{esc(when(record["startedAt"]))} 开始，已完成 '
                      f'{len(record.get("steps") or [])} 步</span>{run_link(record, "查看进度")}</div>'
                      for record in view["running"])
    tiles = "".join(f'<div class="panel tile"><b>{value}</b><span>{label}</span></div>' for value, label in (
        (week["runs"], "7 天内运行"), (week["published"], "发布到 main"), (week["failed"], "未成功"),
        (compact(week["requests"]), "来源请求"), (compact(week["tokens"]), "模型 tokens")))
    cards = "".join(card(item, now) for item in view["cards"])
    chosen = view["filter"]

    def chip(label, **change):
        params = {key: value for key, value in {**chosen, **change}.items() if value}
        selected = all(chosen.get(key) == value for key, value in change.items())
        return (f'<a class="chip" href="/?{esc(urlencode(params))}"{" aria-current=true" if selected else ""}>'
                f'{esc(label)}</a>')

    jobs = chip("全部任务", job=None) + "".join(chip(JOBS[item["job"]], job=item["job"]) for item in view["cards"])
    states = chip("全部结果", status=None) + "".join(
        chip(STATES[state][0], status=state) for state in ("published", "unchanged", "checked", "retry", "failed",
                                                           "interrupted", "running"))
    body = f"""<h1>概览</h1><p class="sub">NAS 上唯一的抓取与发布服务：每个任务一天一次，逐个运行，校验通过后直接推到 main。</p>
{running}<div class="tiles">{tiles}</div>
<h2>各任务</h2><div class="cards">{cards}</div>{legend()}
<h2>运行记录 <span class="muted small">{view["matching"]} 条{"，显示最近 60 条" if view["matching"] > 60 else ""}</span></h2>
<div class="chips">{jobs}</div><div class="chips">{states}</div>
<div class="panel">{runs_table(view["runs"])}</div>"""
    return layout("概览", body, current="overview", stamp=when(view["generatedAt"]))


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
    body = f"""<p class="sub"><a href="/">概览</a> / 任务</p><h1>{esc(JOBS[job])}</h1>
<p class="sub">下次运行：{next_run(view["plan"], runs[0] if runs else None)}</p>
<div class="tiles">{tiles}</div>
<h2>最近 {view["days"]} 天（每天最后一次的结果）</h2><div class="panel" style="padding:14px 16px">
<div class="cal">{cells}</div><div class="cal-axis"><span>{esc(first)}</span><span>今天</span></div>{legend()}</div>
<h2>每次运行</h2><div class="charts">{"".join(charts)}</div>
<p class="muted small">红色柱为未成功的运行。点击柱子进入该次运行。</p>
<h2>运行记录</h2><div class="panel">{runs_table(runs, show_job=False)}</div>"""
    return layout(JOBS[job], body, stamp=when(now.isoformat()))


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
    kv = "".join(f"<dt>{label}</dt><dd>{value}</dd>" for label, value in facts)
    sections = []
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
        sections.append('<h2>审核比对</h2><div class="panel"><dl class="kv">'
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
                        f'<th>全量重读的文件</th></tr></thead><tbody>{rows}</tbody></table></div>')
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
    log_link = f'<a href="/runs/{esc(run)}/log">完整日志</a>' if view["hasLog"] else '<span class="muted">日志已过保留期</span>'
    sections.append(f'<h2>记录与文件</h2><div class="panel scroll"><table><thead><tr><th>{log_link} · '
                    f'<a href="/runs/{esc(run)}/files/status.json">status.json</a></th><th class="num">大小</th></tr></thead>'
                    f'<tbody>{files or "<tr><td class=muted>没有其他文件（产物保留 7 天）</td><td></td></tr>"}</tbody></table></div>')
    body = (f'<p class="sub"><a href="/">概览</a> / <a href="/jobs/{esc(record["job"])}">{esc(JOBS[record["job"]])}</a> / 运行</p>'
            f'<h1>{esc(JOBS[record["job"]])} · {esc(when(record["startedAt"]))}</h1>'
            f'<div class="panel" style="margin-top:14px"><dl class="kv">{kv}</dl></div>' + "".join(sections))
    return layout("运行详情", body, refresh=15 if record["status"] == "running" else 300)


def courses(view):
    summary = view["summary"]
    days = view["days"]
    tiles = "".join(f'<div class="panel tile"><b>{value}</b><span>{label}</span></div>' for value, label in (
        (summary["files"], "课程文件"), (number(summary["offerings"]), "开讲科目"),
        (f'{summary["covered"]}/{summary["files"]}', f"{len(days)} 天内全量核对过"),
        (esc(summary["oldest"] or "—"), "最早的核对日期"), (summary["unverified"], "从未全量核对")))
    rows = []
    for row in view["files"]:
        reads, changed = set(row["reads"]), set(row["changed"])
        cells = "".join(
            f'<span class="cell{" read" if day in reads else ""}{" changed" if day in changed else ""}" '
            f'title="{esc(day)}{" · 全量重读" if day in reads else ""}{" · 有变化" if day in changed else ""}"></span>'
            for day in days)
        rows.append(f'<tr><td>{esc(row.get("name") or "")}<div class="muted small mono">{esc(row["file"])}</div></td>'
                    f'<td class="num">{number(row["offerings"])}</td>'
                    f'<td class="tab">{esc(row["verified"] or "未核对")}</td><td><div class="grid30">{cells}</div></td></tr>')
    grid = (f'<div class="scroll"><table><thead><tr><th>文件（按上次全量核对排序，越靠前越早轮到）</th>'
            f'<th class="num">科目</th><th>上次全量核对</th><th>{esc(days[0][5:])} → {esc(days[-1][5:])}</th></tr></thead>'
            f'<tbody>{"".join(rows) or "<tr><td colspan=4 class=muted>还没有运行过 Syllabus 抓取</td></tr>"}</tbody></table></div>')
    key = ('<p class="legend"><span><i class="cell" style="background:var(--series)"></i>这天全量重读</span>'
           '<span><i class="cell" style="box-shadow:inset 0 0 0 2px var(--warning)"></i>这天有变化</span>'
           '<span><i class="cell"></i>只读列表</span></p>')
    changes = "".join(
        f'<div class="panel" style="margin-bottom:10px"><div style="padding:10px 12px;display:flex;gap:10px;'
        f'align-items:center;flex-wrap:wrap">{run_link(record)} {badge(record["status"])} {change_summary(record)} '
        f'{commit_link(record)}</div>' + "".join(course_items(change) for change in record["changes"]) + "</div>"
        for record in view["changes"]) or '<p class="muted">最近没有课程变化</p>'
    body = f"""<h1>课程文件轮转</h1><p class="sub">每天读全部日文列表页；按文件轮转，每天约 1/30 的课程全量重读（英文列表与详情页）。一次一个请求，间隔 0.5 秒。</p>
<div class="tiles">{tiles}</div><h2>各文件的核对情况</h2><div class="panel">{grid}</div>{key}
<h2>最近的课程变化</h2>{changes}"""
    return layout("课程轮转", body, current="courses")
