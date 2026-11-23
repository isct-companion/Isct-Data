#!/usr/bin/env python3
"""Read the public Science Tokyo syllabus (理工学系) into the course catalog files.

The syllabus lists every offering of a year under the units that offer it
(`/courses/{year}/{school}/{unit}`), one page per unit and language, and one
detail page per offering. The listing gives the code, titles, instructors,
quarter and the syllabus update date; the detail page gives the schedule,
rooms, credits, class format and language. The reader is deterministic: no
model reads these pages, and a page that does not have the expected shape
stops the run instead of publishing a guess.
"""
import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

from check_exam_sources import fetch as fetch_allowed

ROOT = Path(__file__).resolve().parent.parent
HOST = "syllabus.s.isct.ac.jp"
ORIGIN = f"https://{HOST}"
# One request at a time, this far apart: the run is a background read of a
# public site, and its duration does not matter.
SPACING_SECONDS = 0.5
RETRIES = 2
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
DAYS = "月火水木金土日"


# -- HTML ---------------------------------------------------------------------

class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.children, self.parent = tag, dict(attrs), [], parent

    def text(self):
        parts = []
        for child in self.children:
            parts.append(child if isinstance(child, str) else child.text())
        return "".join(parts)

    def clean(self):
        return re.sub(r"\s+", " ", self.text()).strip()

    def classes(self):
        return set((self.attrs.get("class") or "").split())

    def find_all(self, tag=None, cls=None):
        for child in self.children:
            if isinstance(child, Node):
                if (tag is None or child.tag == tag) and (cls is None or cls in child.classes()):
                    yield child
                yield from child.find_all(tag, cls)

    def find(self, tag=None, cls=None):
        return next(self.find_all(tag, cls), None)

    def kids(self, tag):
        return [child for child in self.children if isinstance(child, Node) and child.tag == tag]


class TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#document", (), None)
        self.current = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.current)
        self.current.children.append(node)
        if tag not in VOID:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        self.current.children.append(Node(tag, attrs, self.current))

    def handle_endtag(self, tag):
        node = self.current
        while node is not self.root and node.tag != tag:
            node = node.parent
        if node is not self.root:
            self.current = node.parent

    def handle_data(self, data):
        self.current.children.append(data)


def parse(html):
    builder = TreeBuilder()
    builder.feed(html)
    builder.close()
    return builder.root


class ShapeError(ValueError):
    """A page does not have the shape this reader knows."""


# -- Pages --------------------------------------------------------------------

def unit_path(year, school, unit):
    return f"/courses/{year}/{school}/{unit}"


LEVELS = {
    ("学院等開講科目", "学士課程"): "undergraduate",
    ("学院等開講科目", "大学院課程"): "graduate",
    ("H27年度以前入学者向け", "学士課程"): "legacy-undergraduate",
    ("H27年度以前入学者向け", "大学院課程"): "legacy-graduate",
}
PROGRAMS = "学位プログラムとして特別に設けた教育課程"


def walk(node):
    for child in node.children:
        if isinstance(child, Node):
            yield child
            yield from walk(child)


def parse_year(html, year):
    """The units of a year page, each once: the school id from its URL, its name, the section
    (学士課程, 大学院課程, …) it is listed under and the unit it is listed beneath."""
    units, seen = [], set()
    pattern = re.compile(rf"^{re.escape(ORIGIN)}/courses/{year}/(\d+)/([0-9-]+)$")
    section = subsection = None
    for node in walk(parse(html)):
        if node.tag == "h2":
            section, subsection = node.clean(), None
        elif node.tag == "h3":
            subsection = node.clean()
        elif node.tag == "a":
            found = pattern.match(node.attrs.get("href") or "")
            if not found or found[2] in seen:
                continue
            level = "program" if section == PROGRAMS else LEVELS.get((section, subsection))
            # The page's side menu links each section's own landing unit, named after the section;
            # only the degree programs' one is not also in the main list.
            if level is None and node.clean() == PROGRAMS:
                level = "program"
            if level is None:
                raise ShapeError(f"unit {found[2]} is under an unknown section {section!r} / {subsection!r}")
            seen.add(found[2])
            unit = {"school": found[1], "unit": found[2], "level": level, "name": node.clean()}
            item = node.parent if node.parent.tag == "li" else None
            above = item.parent.parent if item is not None and item.parent is not None else None
            if above is not None and above.tag == "li":
                link = next((child for child in above.kids("a")), None)
                parent = pattern.match(link.attrs.get("href") or "") if link is not None else None
                if parent:
                    unit["parent"] = parent[2]
            units.append(unit)
    if not units:
        raise ShapeError("the year page lists no units")
    return units


LISTING_HEADER = {"ja": "科目コード", "en": "Course Code"}


def unit_names(html, year):
    """Unit id → name, from a year page in any language (its links may carry `?hl=`)."""
    pattern = re.compile(rf"^{re.escape(ORIGIN)}/courses/{year}/\d+/([0-9-]+)(?:\?hl=(?:ja|en))?$")
    names = {}
    for link in parse(html).find_all("a"):
        found = pattern.match(link.attrs.get("href") or "")
        if found and found[1] not in names and link.clean():
            names[found[1]] = link.clean()
    return names


def parse_listing(html, year, lang):
    """Rows of a unit listing in `lang`: id, code, title, instructors, unit label, quarter text, update date."""
    rows = []
    detail = re.compile(rf"^{re.escape(ORIGIN)}/courses/{year}/\d+/[0-9-]+/(\d{{9}})(?:\?hl=(?:ja|en))?$")
    for table in parse(html).find_all("table"):
        head = table.find("thead")
        if head is None or head.find("th") is None or head.find("th").clean() != LISTING_HEADER[lang]:
            raise ShapeError(f"a listing table is not the {lang} course list")
        body = table.find("tbody")
        for row in body.kids("tr") if body else []:
            cells = row.kids("td")
            if len(cells) != 6:
                raise ShapeError(f"a listing row has {len(cells)} cells")
            link = cells[1].find("a")
            found = detail.match(link.attrs.get("href") or "") if link else None
            if not found:
                raise ShapeError("a listing row has no detail link")
            instructors = [name.strip() for name in cells[2].clean().split(" / ")]
            rows.append({
                "id": found[1],
                "code": cells[0].clean(),
                "title": link.clean(),
                "instructors": [name for name in instructors if name],
                "unit": cells[3].clean(),
                "quarter": cells[4].clean(),
                "updated": cells[5].clean(),
            })
    return rows


DETAIL_FIELDS = {
    "開講元": "unit", "担当教員": "instructors", "授業形態": "format", "メディア利用科目": "media",
    "曜日・時限(講義室)": "schedule", "クラス": "class", "科目コード": "code", "単位数": "credits",
    "開講時期": "year", "開講クォーター": "quarter", "シラバス更新日": "updated", "使用言語": "language",
}


def parse_detail(html):
    """The fact list of a Japanese detail page, by field; credits as the three numbers it shows."""
    document = parse(html)
    facts = {}
    for item in document.find_all("div", "c-dl-2col__item"):
        term, value = item.find("dt"), item.find("dd")
        if term is None or value is None:
            raise ShapeError("a detail fact has no term or value")
        name = re.sub(r"\s+", "", term.text())
        field = DETAIL_FIELDS.get(name)
        if field is None:
            continue
        facts[field] = [span.clean() for span in value.kids("span")] if field == "credits" else value.clean()
    missing = sorted(set(DETAIL_FIELDS.values()) - set(facts))
    if missing:
        raise ShapeError(f"a detail page lacks {', '.join(missing)}")
    heading = document.find("h1")
    facts["title"] = heading.clean() if heading else ""
    return facts


# -- Values -------------------------------------------------------------------

def quarters(text):
    """`3～4Q`, `1Q`, `2026 1～2Q`, `1・3Q` → [3, 4], [1], [1, 2], [1, 3]; anything else stops the run."""
    found = re.fullmatch(r"(?:\d{4}\s+)?([1-4～〜~・-]+)Q", text.strip())
    if not found:
        raise ShapeError(f"unknown quarter text: {text!r}")
    result = []
    for part in found[1].split("・"):
        span = re.fullmatch(r"([1-4])(?:[～〜~-]([1-4]))?", part)
        if not span or int(span[2] or span[1]) < int(span[1]):
            raise ShapeError(f"unknown quarter text: {text!r}")
        result.extend(range(int(span[1]), int(span[2] or span[1]) + 1))
    if result != sorted(set(result)):
        raise ShapeError(f"quarters repeat or run backwards: {text!r}")
    return result


def iso_date(text):
    """`2026年9月17日` or `2026/9/17` → `2026-09-17`; `None` for an offering whose syllabus is not written
    yet (the listing leaves the date empty, the detail page prints `-`)."""
    if text.strip() in ("", "-"):
        return None
    found = re.fullmatch(r"(\d{4})(?:年|/)(\d{1,2})(?:月|/)(\d{1,2})日?", text.strip())
    if not found:
        raise ShapeError(f"unknown date text: {text!r}")
    return f"{int(found[1]):04d}-{int(found[2]):02d}-{int(found[3]):02d}"


def number(text):
    if not re.fullmatch(r"\d+(?:\.\d+)?", text):
        raise ShapeError(f"unknown credit amount: {text!r}")
    value = float(text)
    return int(value) if value.is_integer() else value


SLOT_KINDS = {"オンデマンド": "on-demand", "集中講義等": "intensive", "申告専用": "registration-only", "未定": "tba"}


def schedule(text):
    """The slots of `曜日・時限(講義室)`, split on ` / `; each may name its room in parentheses,
    kept as published."""
    if text in ("", "-"):
        return []
    slots = []
    for part in text.split(" / "):
        found = re.fullmatch(r"(.+?)(?:\s*\((.*)\))?", part.strip())
        head, room = found[1].strip(), (found[2] or "").strip()
        weekly = re.fullmatch(r"([月火水木金土日])(\d{1,2})-(\d{1,2})", head)
        if weekly:
            start, end = int(weekly[2]), int(weekly[3])
            if not 1 <= start <= end <= 14:
                raise ShapeError(f"unknown periods: {part!r}")
            slot = {"kind": "weekly", "day": DAYS.index(weekly[1]) + 1, "periods": [start, end]}
        else:
            # A non-weekly arrangement, sometimes with its periods (`集中講義等5-8`).
            named = re.fullmatch(r"(\D+?)(?:(\d{1,2})-(\d{1,2}))?", head)
            if not named:
                raise ShapeError(f"unknown schedule slot: {part!r}")
            word = named[1].strip()
            # Internships, 講究, 特課研 and other arrangements without a kind of their own: named as published.
            slot = {"kind": SLOT_KINDS[word]} if word in SLOT_KINDS else {"kind": "other", "label": word}
            if named[2]:
                start, end = int(named[2]), int(named[3])
                if not 1 <= start <= end <= 14:
                    raise ShapeError(f"unknown periods: {part!r}")
                slot["periods"] = [start, end]
        if room:
            slot["room"] = room
        slots.append(slot)
    return slots


FORMAT_KINDS = {"講義": "lecture", "演習": "exercise", "実験等": "experiment"}
DELIVERY = {"対面型": "in-person", "ハイフレックス型": "hyflex", "ブレンド型": "blended", "ライブ型": "live",
            "オンデマンド型": "on-demand", "その他": "other"}


def class_format(text):
    """`講義/演習 (対面型)` → kinds and delivery; an unknown word stops the run."""
    found = re.fullmatch(r"([^()（）]+?)\s*(?:[(（]([^()（）]+)[)）])?", text.strip())
    if not found:
        raise ShapeError(f"unknown class format: {text!r}")
    kinds = []
    for word in found[1].split("/"):
        if word.strip() not in FORMAT_KINDS:
            raise ShapeError(f"unknown class kind: {word!r}")
        kinds.append(FORMAT_KINDS[word.strip()])
    delivery = None
    if found[2] is not None:
        if found[2].strip() not in DELIVERY:
            raise ShapeError(f"unknown delivery: {found[2]!r}")
        delivery = DELIVERY[found[2].strip()]
    return kinds, delivery


LANGUAGES = {"日本語": "ja", "英語": "en"}


def language(text):
    if text in LANGUAGES:
        return LANGUAGES[text]
    if text in ("", "-"):
        return None
    return "other"


# -- Reading the site ---------------------------------------------------------

class Site:
    """Fetches syllabus pages one at a time, spaced, with a few retries for transient failures.

    `cache` (a directory) keeps raw pages for a development run, so a rerun
    reads nothing twice; the CI run has no cache."""

    def __init__(self, cache=None, spacing=SPACING_SECONDS):
        self.cache, self.spacing, self.last, self.requests = cache, spacing, 0.0, 0

    def get(self, path):
        url = ORIGIN + path
        if self.cache is not None:
            key = self.cache / (hashlib.sha256(url.encode()).hexdigest()[:32] + ".html")
            if key.exists():
                return key.read_text(encoding="utf-8")
        for attempt in range(RETRIES + 1):
            wait = self.last + self.spacing - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self.last = time.monotonic()
            self.requests += 1
            try:
                html = fetch_allowed(url, hosts=(HOST,)).decode("utf-8")
                break
            except HTTPError as error:
                if error.code < 500 or attempt == RETRIES:
                    raise
            except (URLError, TimeoutError):
                if attempt == RETRIES:
                    raise
            time.sleep(5 * (attempt + 1))
        if self.cache is not None:
            self.cache.mkdir(parents=True, exist_ok=True)
            key.write_text(html, encoding="utf-8")
        return html


def read_listings(site, year, units=None, english=None):
    """Every offering a year's units list, by id: the Japanese row, the English row and the units
    listing it. `english(unit_id, ja_rows)` says whether a unit's English listing is read; without
    it every one is. An offering whose units were read only in Japanese has `en` set to `None`."""
    units = units or parse_year(site.get(f"/courses/{year}"), year)
    offerings = {}
    for unit in units:
        path = unit_path(year, unit["school"], unit["unit"])
        ja = parse_listing(site.get(path), year, "ja")
        en = None
        if english is None or english(unit["unit"], ja):
            en = {row["id"]: row for row in parse_listing(site.get(path + "?hl=en"), year, "en")}
            if set(en) != {row["id"] for row in ja}:
                raise ShapeError(f"{path}: the Japanese and English listings differ")
        for row in ja:
            entry = offerings.setdefault(row["id"], {"ja": row, "en": None, "units": []})
            if entry["ja"]["code"] != row["code"] or entry["ja"]["updated"] != row["updated"]:
                raise ShapeError(f"{row['id']} is listed differently under two units")
            if en is not None:
                entry["en"] = en[row["id"]]
            entry["units"].append(unit["unit"])
    return units, offerings


def detail_path(entry):
    # The short form the site itself links from elsewhere; Japanese is the default language, and
    # `?hl=ja` only redirects here.
    return f"/courses/-/-/-/{entry['ja']['id']}"


def record(year, entry, facts, units, known=None):
    """One offering as published: the listings' names in both languages and the detail page's facts."""
    ja = entry["ja"]
    if facts["code"] != ja["code"]:
        raise ShapeError(f"{ja['id']}: the detail code {facts['code']} differs from the listing")
    if iso_date(facts["updated"]) != iso_date(ja["updated"]):
        raise ShapeError(f"{ja['id']}: the detail page and the listing differ in their update date")
    if not facts["year"].startswith(str(year)):
        raise ShapeError(f"{ja['id']}: offered in {facts['year']}, not {year}")
    if quarters(facts["quarter"]) != quarters(ja["quarter"]):
        raise ShapeError(f"{ja['id']}: the detail page and the listing differ in their quarters")
    if len(facts["credits"]) != 3:
        raise ShapeError(f"{ja['id']}: credits are not lecture-exercise-lab")
    lecture, exercise, lab = (number(amount) for amount in facts["credits"])
    kinds, delivery = class_format(facts["format"])
    value = record_from_listing(entry, units, known)
    value = {
        "id": ja["id"],
        **{key: value[key] for key in ("code", "title", "instructors", "unit", "units", "quarters")},
        "schedule": schedule(facts["schedule"]),
        "credits": {"lecture": lecture, "exercise": exercise, "lab": lab},
        "format": {"kinds": kinds, "delivery": delivery},
        "language": language(facts["language"]),
        "syllabusUpdated": iso_date(ja["updated"]),
    }
    if facts["class"] not in ("", "-"):
        value["class"] = facts["class"]
    if facts["media"] not in ("", "-"):
        value["media"] = facts["media"]
    return value


def record_from_listing(entry, units, known=None):
    """The fields a listing alone gives, as `record` writes them. Without this run's English row
    (`entry["en"]` is `None`) the English names come from the published offering `known`; its
    instructors' English names are kept only while the Japanese ones are the same."""
    ja, en = entry["ja"], entry["en"]
    order = {unit["unit"]: position for position, unit in enumerate(units)}
    if en is not None:
        paired = len(en["instructors"]) == len(ja["instructors"])
        instructors = [dict({"ja": name}, **({"en": en["instructors"][i]} if paired else {}))
                       for i, name in enumerate(ja["instructors"])]
        title, unit = {"ja": ja["title"], "en": en["title"]}, {"ja": ja["unit"], "en": en["unit"]}
    elif known is not None:
        same = [name["ja"] for name in known["instructors"]] == ja["instructors"]
        instructors = known["instructors"] if same else [{"ja": name} for name in ja["instructors"]]
        title = dict({"ja": ja["title"]}, **({"en": known["title"]["en"]} if "en" in known["title"] else {}))
        unit = dict({"ja": ja["unit"]}, **({"en": known["unit"]["en"]} if "en" in known["unit"] else {}))
    else:
        raise ShapeError(f"{ja['id']} is new but none of its English listings was read")
    return {
        "code": ja["code"],
        "title": title,
        "instructors": instructors,
        "unit": unit,
        "units": sorted(entry["units"], key=order.__getitem__),
        "quarters": quarters(ja["quarter"]),
        "syllabusUpdated": iso_date(ja["updated"]),
    }


# -- Files --------------------------------------------------------------------

LEVEL_NAMES = {
    "undergraduate": {"ja": "学士課程", "en": "Undergraduate"},
    "graduate": {"ja": "大学院課程", "en": "Graduate"},
    "program": {"ja": "学位プログラムとして特別に設けた教育課程", "en": "Special degree programs"},
    "legacy": {"ja": "H27年度以前入学者向け", "en": "For students admitted in or before 2015"},
}
# Each file is read again in full (its English listings and every detail page) about this often:
# the files due on a run hold about 1/ROTATION_DAYS of the year's offerings.
ROTATION_DAYS = 30


def group_of(unit):
    """The file a unit's offerings go to: its school within its level; programs and the
    pre-2016 curricula each in one file."""
    if unit["level"] in ("undergraduate", "graduate"):
        return f"{unit['level']}-{unit['school']}"
    return "legacy" if unit["level"].startswith("legacy") else "programs"


def file_name(year, group):
    return f"courses/{year}/{group}.json"


def group_name(group, units):
    level = {"programs": "program"}.get(group, group.split("-")[0])
    name = dict(LEVEL_NAMES[level])
    if level in ("undergraduate", "graduate"):
        top = next(unit for unit in units if "parent" not in unit)
        name = {lang: f"{top['name'][lang]} {name[lang]}" if lang in top["name"] else name[lang]
                for lang in ("ja", "en") if lang in name}
    return name


def due_files(names, sizes, verified, *, full=False):
    """The files read in full this run: the least recently verified one (never verified before any),
    then, in the same order, each further file that still fits about 1/ROTATION_DAYS of the
    offerings; every file when `full` or when nothing is published yet. A file larger than the
    share is read alone on the run it is the oldest."""
    total = sum(sizes.values())
    if full or not total:
        return set(names)
    budget = max(1, total // ROTATION_DAYS)
    chosen, held = set(), 0
    for name in sorted(names, key=lambda name: (verified.get(name, ""), name)):
        if chosen and held + sizes.get(name, 0) > budget:
            continue
        chosen.add(name)
        held += sizes.get(name, 0)
    return chosen


def build(site, year, previous=None, verified=None, *, full=False):
    """The year's files by path, and the files read in full this run. Every unit's Japanese listing
    is read; a unit's English listing only when the unit belongs to a due file or lists a new or
    changed offering (its syllabus update date moved); an offering's detail page only when it is new,
    changed or in a due file. `previous` maps published offering ids to (file, offering);
    `verified` maps file names to the date of their last full read."""
    previous, verified = previous or {}, verified or {}
    units = parse_year(site.get(f"/courses/{year}"), year)
    english = unit_names(site.get(f"/courses/{year}?hl=en"), year)
    for unit in units:
        unit["name"] = {"ja": unit["name"], **({"en": english[unit["unit"]]} if english.get(unit["unit"]) else {})}
    by_unit = {unit["unit"]: unit for unit in units}
    names = sorted({file_name(year, group_of(unit)) for unit in units})
    sizes = {name: sum(1 for file, _ in previous.values() if file == name) for name in names}
    due = due_files(names, sizes, verified, full=full)

    def moved(row):
        known = previous.get(row["id"])
        return known is None or known[1]["syllabusUpdated"] != iso_date(row["updated"])

    def wants_english(unit_id, rows):
        return file_name(year, group_of(by_unit[unit_id])) in due or any(moved(row) for row in rows)

    _, offerings = read_listings(site, year, units=units, english=wants_english)
    order = {unit["unit"]: position for position, unit in enumerate(units)}
    files = {}
    for unit in units:
        files.setdefault(group_of(unit), {"units": [], "offerings": []})["units"].append(unit)
    for offering_id in sorted(offerings):
        entry = offerings[offering_id]
        entry["units"].sort(key=order.__getitem__)
        group = group_of(by_unit[entry["units"][0]])
        known = previous.get(offering_id, (None, None))[1]
        if known is not None and file_name(year, group) not in due and not moved(entry["ja"]):
            # Unchanged syllabus outside this run's rotation: the listing's fields are taken fresh and
            # the detail facts kept. An offering without a syllabus keeps `None` until one is written.
            value = dict(known)
            value.update(record_from_listing(entry, units, known))
        else:
            value = record(year, entry, parse_detail(site.get(detail_path(entry))), units, known)
        files[group]["offerings"].append(value)
    published = {}
    for group, content in sorted(files.items()):
        published[file_name(year, group)] = {
            "schemaVersion": 1,
            "academicYear": year,
            "group": {"id": group, "name": group_name(group, content["units"])},
            "source": [{"id": "syllabus", "url": f"{ORIGIN}/courses/{year}"}],
            "units": [{key: unit[key] for key in ("id", "school", "level", "name", "parent") if key in unit}
                      for unit in ({**unit, "id": unit["unit"]} for unit in content["units"])],
            "offerings": content["offerings"],
        }
    return published, due


# -- Command ------------------------------------------------------------------

# A run that would drop this share of a year's offerings is not written: a site
# that answers a near-empty listing must not empty the catalog.
MAX_SHRINK = 0.2
REPOSITORY = "isct-companion/Isct-Data"


def published_offerings(root, year):
    """Offering id → (file name, offering) for the year's published files."""
    offerings = {}
    for path in sorted((root / "courses" / str(year)).glob("*.json")):
        name = path.relative_to(root).as_posix()
        for offering in json.loads(path.read_text(encoding="utf-8"))["offerings"]:
            offerings[offering["id"]] = (name, offering)
    return offerings


def academic_year(now):
    japan = now.astimezone(timezone.utc).timestamp() + 9 * 3600
    today = datetime.fromtimestamp(japan, timezone.utc)
    return today.year - (1 if today.month < 4 else 0)


def serialize(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def write_year(root, year, files):
    """Writes the year's files; a file whose facts did not change keeps its bytes, so its hash in
    the index stays and apps do not download it again."""
    directory = root / "courses" / str(year)
    directory.mkdir(parents=True, exist_ok=True)
    for stale in directory.glob("*.json"):
        if stale.relative_to(root).as_posix() not in files:
            stale.unlink()
    for name, value in files.items():
        path, text = root / name, serialize(value)
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8")


def list_in_index(root, year, names):
    """Lists the year's files under `academicYears.{year}.courses`; `update_subscription_index.py`
    then fills their hashes. A year the index has no academic calendar for is refused: apps read an
    academic-year entry only with its calendar, and an entry without one would break the whole index."""
    path = root / "index.json"
    index = json.loads(path.read_text(encoding="utf-8"))
    entry = index["academicYears"].get(str(year))
    if not entry or "academicCalendar" not in entry:
        raise ShapeError(f"{year} has no academic calendar in index.json; its courses are not listed")
    known = {reference["source"]: reference for reference in entry.get("courses", []) if isinstance(reference, dict)}
    entry["courses"] = [known.get(name, name) for name in sorted(names)]
    path.write_text(serialize(index), encoding="utf-8")


def git(root, *args):
    import subprocess
    return subprocess.check_output(["git", "-c", "core.hooksPath=/dev/null", *args], cwd=root, text=True)


def publication(root, base):
    """The files a pull request carries: course files added, changed or removed since `base`, with
    the index; `{}` when none did. Unchanged files keep their bytes (`write_year`)."""
    names = set(git(root, "diff", "--name-only", base, "--", "courses").split())
    names |= set(git(root, "ls-files", "--others", "--exclude-standard", "--", "courses").split())
    if not names:
        return {}
    changed = {name: (root / name).read_text(encoding="utf-8") if (root / name).exists() else None
               for name in sorted(names)}
    for name in ("index.json", "index.sha256"):
        changed[name] = (root / name).read_text(encoding="utf-8")
    return changed


def github(token, method, path, body=None):
    from urllib.request import Request, urlopen
    url = path if path.startswith("https://") else f"https://api.github.com/repos/{REPOSITORY}/{path}"
    request = Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                      headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                               "Content-Type": "application/json", "User-Agent": "Isct-Data-syllabus-reader"})
    try:
        with urlopen(request, timeout=60) as response:
            return json.load(response)
    except HTTPError as error:
        raise ValueError(f"GitHub API {method} {path} failed with HTTP {error.code}") from None


def publish(root, base, token, label):
    """Open a catalog PR and request auto-merge if the repository allows it."""
    files = publication(root, base)
    if not files:
        return {"changed": False}
    if not token:
        raise ValueError("publisher credentials are missing")
    if github(token, "GET", "git/ref/heads/main")["object"]["sha"] != base:
        raise ValueError("main advanced during the read; the next run publishes on the latest main")
    waiting = [pull for pull in github(token, "GET", "pulls?state=open&base=main&per_page=100")
               if pull["head"]["ref"].startswith("automation/courses/")]
    if waiting:
        return {"changed": True, "held": waiting[0]["html_url"]}
    settings = github(token, "GET", f"https://api.github.com/repos/{REPOSITORY}")
    auto_merge = settings.get("allow_auto_merge", False)
    branch = f"automation/courses/{label}"
    original = github(token, "GET", f"git/commits/{base}")
    tree = github(token, "POST", "git/trees", {"base_tree": original["tree"]["sha"], "tree": [
        {"path": name, "mode": "100644", "type": "blob", **({"content": text} if text is not None else {"sha": None})}
        for name, text in files.items()]})
    commit = github(token, "POST", "git/commits", {"message": "Update the course catalog", "tree": tree["sha"],
                                                    "parents": [base]})
    github(token, "POST", "git/refs", {"ref": f"refs/heads/{branch}", "sha": commit["sha"]})
    courses = sorted(name for name in files if name.startswith("courses/"))
    body = (f"Read from the public syllabus <{ORIGIN}> on {label} by the syllabus reader (docs/courses.md).\n\n"
            "Changed files\n\n"
            + "\n".join(f"- `{name}`" + (" (removed)" if files[name] is None else "") for name in courses)
            + ("\n\nAuto-merge requested after CI passes." if auto_merge
               else "\n\nPlease squash merge after the required CI passes."))
    pull = github(token, "POST", "pulls", {"title": "Update the course catalog", "head": branch, "base": "main",
                                          "body": body})
    result = {"changed": True, "pullRequest": pull["html_url"], "files": courses, "autoMerge": False}
    if not auto_merge:
        return result
    merge = github(token, "POST", "https://api.github.com/graphql", {
        "query": "mutation($id: ID!) { enablePullRequestAutoMerge(input: {pullRequestId: $id, mergeMethod: SQUASH})"
                 " { pullRequest { number } } }",
        "variables": {"id": pull["node_id"]}})
    if merge.get("errors"):
        raise ValueError(f"auto-merge was not turned on for {pull['html_url']}: {merge['errors'][0].get('message')}")
    return dict(result, autoMerge=True)


def read_state(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"verified": {}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--year", type=int, action="append",
                        help="academic year to read (repeatable); default: the current one, and the next once published")
    parser.add_argument("--full", action="store_true", help="read every file in full")
    parser.add_argument("--state", type=Path, help="the rotation state (each file's last full read); "
                        "without it every file is due")
    parser.add_argument("--cache", type=Path, help="keep raw pages here (development runs only)")
    parser.add_argument("--publish", metavar="BASE_SHA",
                        help="open an auto-merging pull request with what a previous run wrote, against this main commit")
    args = parser.parse_args()
    root = args.root.resolve()
    # The date in Japan, when the reader runs.
    today = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() + 9 * 3600, timezone.utc).date().isoformat()
    if args.publish:
        import os
        try:
            result = publish(root, args.publish, os.environ.get("GITHUB_TOKEN"), today)
        except (OSError, ValueError, KeyError) as error:
            print(f"course catalog publication failed: {error}", file=sys.stderr)
            return 2
        print(json.dumps(result))
        return 0
    site = Site(cache=args.cache)
    state = read_state(args.state) if args.state else {"verified": {}}
    years = args.year
    if not years:
        current = academic_year(datetime.now(timezone.utc))
        years = [current]
        try:
            parse_year(site.get(f"/courses/{current + 1}"), current + 1)
            years.append(current + 1)
        except (HTTPError, ShapeError):
            pass
    summary, verified = [], dict(state["verified"])
    try:
        for year in years:
            index = json.loads((root / "index.json").read_text(encoding="utf-8"))
            if "academicCalendar" not in index["academicYears"].get(str(year), {}):
                # See `list_in_index`: nothing is read for a year that cannot be listed.
                summary.append({"year": year, "skipped": "no academic calendar in index.json yet"})
                continue
            previous = published_offerings(root, year)
            files, due = build(site, year, previous, state["verified"] if args.state else {}, full=args.full)
            count = sum(len(value["offerings"]) for value in files.values())
            if previous and count < len(previous) * (1 - MAX_SHRINK):
                raise ShapeError(f"{year}: {count} offerings against {len(previous)} published; not written")
            write_year(root, year, files)
            list_in_index(root, year, files)
            verified.update({name: today for name in due})
            summary.append({"year": year, "files": len(files), "offerings": count, "readInFull": sorted(due)})
    except (ShapeError, HTTPError, URLError, TimeoutError) as error:
        print(f"syllabus read failed after {site.requests} requests: {error}", file=sys.stderr)
        return 2
    if args.state:
        # Written beside the state; the runner moves it over the state once the result is published.
        args.state.with_suffix(".pending.json").write_text(serialize({"verified": verified}), encoding="utf-8")
    print(json.dumps({"requests": site.requests, "years": summary}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
