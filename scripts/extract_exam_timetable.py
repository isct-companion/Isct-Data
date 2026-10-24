#!/usr/bin/env python3
"""Read the official exam-week timetable PDF cell by cell.

The PDF draws its table with thin black rectangles, marks revisions in red and
strikes withdrawn values with thin red rectangles. Plain text extraction loses
all three, so this reader works from page geometry: words are assigned to grid
cells (a merged cell keeps its whole extent), struck words are dropped, a row
whose course code is struck is a withdrawn row, and text right of the table is
a margin note rather than a cell value. The output is a reviewable list of rows;
publishing is a separate step.
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pdfplumber

COLUMNS = ("date", "type", "periods", "code", "title", "instructors", "room")
CODE = re.compile(r"^[A-Z]{3}\.[A-Z]\d{3}(?:-\d{2})?$")
PERIODS = re.compile(r"^(\d{1,2})-(\d{1,2})$")
DAY = re.compile(r"^(\d{1,2})[(（]")
TYPES = {"期末試験": "exam", "授業": "class"}
NOTE_MARKS = ("*", "※")


def is_red(color):
    return (
        isinstance(color, (tuple, list))
        and len(color) == 3
        and color[0] > 0.8
        and color[1] < 0.2
        and color[2] < 0.2
    )


def is_black(color):
    if isinstance(color, (int, float)):
        return color < 0.2
    return isinstance(color, (tuple, list)) and len(color) in (1, 3) and max(color) < 0.2


def grid(page):
    """Column edges from tall black rules, plus every row rule with the
    x-range it crosses, so a merged cell (a rule missing in its column) stays
    one cell."""
    rects = [r for r in page.rects if r["fill"] and is_black(r.get("non_stroking_color"))]
    # Column rules may be drawn as separate header and body segments.
    vertical = sorted(
        {round(r["x0"], 1) for r in rects if r["bottom"] - r["top"] > 20 and r["x1"] - r["x0"] < 3}
    )
    rules = [(round(r["top"], 1), r["x0"], r["x1"]) for r in rects if r["x1"] - r["x0"] > 20 and r["bottom"] - r["top"] < 3]
    if len(vertical) != len(COLUMNS) + 1 or len(rules) < 2:
        raise ValueError(f"page {page.page_number}: expected a {len(COLUMNS)}-column table grid")
    return vertical, rules


def crossing(rules, left, right):
    """Rule positions that separate rows within one column."""
    return sorted({top for top, x0, x1 in rules if x0 <= left + 2 and x1 >= right - 2})


def strikes(page):
    return [
        r for r in page.rects
        if r["fill"] and is_red(r.get("non_stroking_color")) and r["bottom"] - r["top"] < 3
    ]


def struck(word, lines):
    """A strike line crosses the word's middle half and most of its width."""
    height = word["bottom"] - word["top"]
    for line in lines:
        middle = (line["top"] + line["bottom"]) / 2
        overlap = min(word["x1"], line["x1"]) - max(word["x0"], line["x0"])
        if word["top"] + height / 4 < middle < word["bottom"] - height / 4 and overlap > (word["x1"] - word["x0"]) * 0.6:
            return True
    return False


def centre(word):
    return (word["x0"] + word["x1"]) / 2, (word["top"] + word["bottom"]) / 2


def text_lines(words):
    """Group a cell's words into visual lines, top to bottom."""
    lines = []
    for word in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        if lines and abs(lines[-1][0]["top"] - word["top"]) < 3:
            lines[-1].append(word)
        else:
            lines.append([word])
    return [" ".join(w["text"] for w in sorted(line, key=lambda w: w["x0"])) for line in lines]


def room_cell(words):
    """Room cell text as published, and its explanatory note. A room code
    broken after a hyphen or comma is rejoined; the note starts at the first
    line marked * or ※ and runs to the end of the cell."""
    lines = text_lines(words)
    split = next((i for i, line in enumerate(lines) if line.startswith(NOTE_MARKS)), len(lines))
    joined = ""
    for line in lines[:split]:
        joined += line if not joined or joined.endswith(("-", ",")) else " " + line
    room = re.sub(r"\s*,\s*", ",", joined.replace("\u3000", " ")).strip()
    return room, " ".join(lines[split:]) or None


def resolve_date(day_cell, exam_range):
    """The table prints only the day; it is unique within one exam period."""
    match = DAY.match(day_cell)
    if not match:
        raise ValueError(f"unreadable date cell: {day_cell!r}")
    day = int(match.group(1))
    start, end = (date.fromisoformat(value) for value in exam_range)
    days = [start + timedelta(days=n) for n in range((end - start).days + 1)]
    matches = [value for value in days if value.day == day]
    if len(matches) != 1:
        raise ValueError(f"date {day_cell!r} is not unique within {exam_range}")
    return matches[0].isoformat()


def read_page(page, exam_range):
    try:
        columns, rules = grid(page)
    except ValueError:
        return []
    lines = strikes(page)
    words = page.extract_words(extra_attrs=["non_stroking_color"])
    margin = [w for w in words if w["x0"] >= columns[-1]]
    column_edges = [crossing(rules, columns[i], columns[i + 1]) for i in range(len(COLUMNS))]
    edges = column_edges[COLUMNS.index("code")]
    rows = []
    for top, bottom in zip(edges, edges[1:]):
        cells = {name: [] for name in COLUMNS}
        removed = {name: [] for name in COLUMNS}
        for index, name in enumerate(COLUMNS):
            above = max((edge for edge in column_edges[index] if edge <= top + 1), default=top)
            below = min((edge for edge in column_edges[index] if edge >= bottom - 1), default=bottom)
            for word in words:
                x, y = centre(word)
                if columns[index] <= x < columns[index + 1] and above <= y < below:
                    (removed if struck(word, lines) else cells)[name].append(word)
        kind_lines = text_lines(cells["type"] + removed["type"])
        kind = next((TYPES[value] for value in TYPES if any(line.startswith(value) for line in kind_lines)), None)
        if kind is None:
            continue  # column headings
        live = lambda name: cells[name] or removed[name]
        title = text_lines(live("title"))
        # The Japanese title comes first and may wrap; the official English
        # title starts on a later line with a Latin letter.
        english_from = next((i for i, line in enumerate(title) if i and re.match(r"[A-Za-z]", line)), len(title))
        codes = [token for token in re.split(r"[\s,、]+", " ".join(text_lines(live("code")))) if CODE.match(token)]
        period_text = "".join(text_lines(live("periods")))
        period_match = PERIODS.match(period_text)
        room, room_note = room_cell(cells["room"])
        own = [w for w in cells.values() for w in w]
        note = " ".join(text_lines([w for w in margin if top <= centre(w)[1] < bottom]))
        rows.append({
            "page": page.page_number,
            "kind": kind,
            "date": resolve_date("".join(text_lines(live("date"))), exam_range),
            "periods": [int(period_match.group(1)), int(period_match.group(2))] if period_match else None,
            "periodText": period_text,
            "codes": codes,
            "titleJa": " ".join(title[:english_from]),
            "titleEn": " ".join(title[english_from:]),
            "instructors": " ".join(text_lines(cells["instructors"])),
            "room": room,
            "roomNote": room_note,
            "struck": {name: [w["text"] for w in value] for name, value in removed.items() if value},
            "withdrawn": bool(removed["code"]) and not cells["code"],
            "revised": any(is_red(w.get("non_stroking_color")) for w in own),
            "note": note or None,
        })
    return rows


def read_rows(pdf_path, exam_range):
    with pdfplumber.open(pdf_path) as pdf:
        return [row for page in pdf.pages for row in read_page(page, exam_range)]


def exam_drift(rows, feed, source_id):
    """Disagreements between this PDF's exam rows and the reviewed exam feed.

    Both come from the same PDF, so agreement checks the reader; drift means
    the PDF changed or one of them is wrong, and needs review before either
    feed is published."""
    published = {
        (entry["courseCode"], entry["date"], tuple(entry.get("periods") or ())): entry
        for entry in feed["entries"]
        if source_id in entry["sourceIds"]
    }
    seen = set()
    problems = []
    for row in rows:
        if row["kind"] != "exam":
            continue
        for code in row["codes"]:
            key = (code, row["date"], tuple(row["periods"] or ()))
            entry = published.get(key)
            if row["withdrawn"]:
                if entry and entry["status"] != "cancelled":
                    problems.append(f"{key}: withdrawn in the PDF but published as scheduled")
                seen.add(key)
                continue
            if entry is None:
                problems.append(f"{key}: in the PDF but not in the exam feed")
                continue
            seen.add(key)
            room = entry["room"]["ja"] if entry.get("room") else ""
            label = entry["label"]
            if (row["room"], row["titleJa"], row["titleEn"]) != (room, label["ja"], label.get("en", "")):
                problems.append(f"{key}: room or title differs from the exam feed")
    problems.extend(f"{key}: in the exam feed but not in the PDF" for key in sorted(set(published) - seen))
    return problems


def class_feed(rows, *, year, quarter, level, source):
    """The exam-week class feed for one level and quarter. A withdrawn row is
    left out; the slot (course, date, first period) names a session."""
    entries = []
    for row in rows:
        if row["kind"] != "class" or row["withdrawn"]:
            continue
        if len(row["codes"]) != 1 or not row["periods"] or not row["titleJa"]:
            raise ValueError(f"page {row['page']}: unreadable class row {row['codes']} {row['periodText']!r}")
        code = row["codes"][0]
        label = {"ja": row["titleJa"]}
        if row["titleEn"]:
            label["en"] = row["titleEn"]
        entries.append({
            "id": f"{year}-{quarter}-{level}-{code}-class-{row['date']}-{row['periods'][0]}",
            "kind": "class",
            "status": "scheduled",
            "quarter": quarter,
            "courseCode": code,
            "date": row["date"],
            "periods": row["periods"],
            "room": {"ja": row["room"]} if row["room"] else None,
            "label": label,
            "sourceIds": [source["id"]],
            "sourcePages": [row["page"]],
        })
    ids = [entry["id"] for entry in entries]
    if len(ids) != len(set(ids)):
        raise ValueError("two class rows share a course, date and first period")
    return {"schemaVersion": 1, "academicYear": year, "timezone": "Asia/Tokyo", "source": [source], "entries": entries}


def extract_classes(pdf, *, calendar, quarter, level, manifest, exam_feed, retrieved_at=None):
    ranges = calendar.get("examRanges", {}).get(quarter, [])
    if not ranges:
        raise ValueError(f"no exam range for {quarter}")
    if exam_feed["academicYear"] != calendar["academicYear"]:
        raise ValueError("exam feed and calendar academic year differ")
    with pdfplumber.open(pdf) as document:
        heading = (document.pages[0].extract_text() or "")[:500] if document.pages else ""
    scope = re.search(r"Schedule of Final Exams(?: and Classes)?\s*-\s*(\d{4})\s+([1-4]Q)\s*-", heading)
    if not scope or (int(scope[1]), scope[2]) != (calendar["academicYear"], quarter):
        raise ValueError("PDF year/quarter heading differs from the selected scope or is unreadable")
    expected_level = "大学院課程" if level == "graduate" else "学士課程"
    if expected_level not in heading:
        raise ValueError("PDF level heading differs from the selected scope or is unreadable")
    rows = read_rows(pdf, (ranges[0]["start"], ranges[-1]["end"]))
    if not rows:
        raise ValueError("no timetable rows recognized; refusing to publish an empty extraction")
    official = [
        source for source in manifest["sources"]
        if source["level"] == level and source["scope"] == "central_final_exam_timetable"
    ]
    if len(official) != 1 or manifest["academicYear"] != calendar["academicYear"] or manifest["quarter"] != quarter:
        raise ValueError("the manifest must name one central timetable for this level, year and quarter")
    drift = exam_drift(rows, exam_feed, official[0]["id"])
    if drift:
        raise ValueError("exam rows disagree with the reviewed exam feed: " + "; ".join(drift))
    published = next(source for source in exam_feed["source"] if source["id"] == official[0]["id"])
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    source = {
        "id": official[0]["id"],
        "title": published["title"],
        "url": official[0]["artifactUrl"],
        "landingPageUrl": official[0]["url"],
        "retrievedAt": retrieved,
        "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
    }
    if "publishedAt" in published:
        source["publishedAt"] = published["publishedAt"]
    return class_feed(rows, year=calendar["academicYear"], quarter=quarter, level=level, source=source)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    rows_command = commands.add_parser("rows", help="write every table row for review")
    classes_command = commands.add_parser("classes", help="write the exam-week class feed")
    for command in (rows_command, classes_command):
        command.add_argument("pdf", type=Path)
        command.add_argument("--calendar", type=Path, required=True, help="academic-calendar/YEAR.json")
        command.add_argument("--quarter", choices=("1Q", "2Q", "3Q", "4Q"), required=True)
        command.add_argument("--output", type=Path, required=True)
    classes_command.add_argument("--level", choices=("undergraduate", "graduate"), required=True)
    classes_command.add_argument("--manifest", type=Path, required=True, help="source-manifest/YEAR-quarter.json")
    classes_command.add_argument("--exam-feed", type=Path, required=True, help="exam/LEVEL/YEAR-quarter.json from the same PDF")
    classes_command.add_argument("--retrieved-at", help="RFC 3339 time the PDF was fetched (default: now)")
    args = parser.parse_args()
    calendar = json.loads(args.calendar.read_text(encoding="utf-8"))
    ranges = calendar.get("examRanges", {}).get(args.quarter, [])
    if not ranges:
        print(f"no exam range for {args.quarter}", file=sys.stderr)
        return 2
    if args.command == "rows":
        rows = read_rows(args.pdf, (ranges[0]["start"], ranges[-1]["end"]))
        args.output.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        counts = {kind: sum(row["kind"] == kind for row in rows) for kind in TYPES.values()}
        print(json.dumps({"rows": len(rows), **counts, "withdrawn": sum(row["withdrawn"] for row in rows)}))
        return 0
    try:
        feed = extract_classes(args.pdf, calendar=calendar, quarter=args.quarter,
                               level=args.level,
                               manifest=json.loads(args.manifest.read_text(encoding="utf-8")),
                               exam_feed=json.loads(args.exam_feed.read_text(encoding="utf-8")),
                               retrieved_at=args.retrieved_at)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "entries": len(feed["entries"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
