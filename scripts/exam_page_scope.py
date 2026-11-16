"""Locate a safe page review scope for two public timetable snapshots."""
import hashlib
import json
from collections import Counter
from math import isclose
import re
from unicodedata import normalize

import pdfplumber

from extract_exam_timetable import CODE, crossing, grid, is_red, read_page


def digest(data):
    return hashlib.sha256(data).hexdigest()


def page_objects(page):
    fields = ("text", "x0", "top", "x1", "bottom", "fill",
              "stroking_color", "non_stroking_color")

    return [
        [[item.get(field) for field in fields] for item in objects]
        for objects in (page.chars, page.lines, page.rects, page.curves)
    ]


def annotations(page):
    fields = ("x0", "top", "x1", "bottom", "uri", "title", "contents")
    return [[item.get(field) for field in fields] for item in page.annots]


def page_fingerprints(pdf):
    hashes = []
    for page in pdf.pages:
        image = page.to_image(resolution=96).original.convert('RGB')
        features = [page.bbox, page.cropbox, page.rotation, image.size, digest(image.tobytes()),
                    page_objects(page), annotations(page)]
        hashes.append(digest(json.dumps(features, ensure_ascii=False).encode()))
        page.close()
    return hashes


LOCAL_REVISION = re.compile(r"(?:\d{1,2}/\d{1,2}\([月火水木金土日]\)\s*)?(?:追加|修正|講義室変更)")


def page_context(page, date_range):
    """Check table coverage and collect text whose meaning can extend beyond a row."""
    columns, rules = grid(page)
    edges = crossing(rules, columns[3], columns[4])
    rows = read_page(page, date_range)
    if not rows or any(not row["codes"] or row["periods"] is None for row in rows):
        raise ValueError("incomplete table extraction")
    words = page.extract_words()
    code_words = []
    for word in words:
        x = (word["x0"] + word["x1"]) / 2
        y = (word["top"] + word["bottom"]) / 2
        if columns[3] <= x < columns[4] and edges[0] <= y <= edges[-1]:
            for code in re.split(r"[,、]", word["text"]):
                if CODE.fullmatch(code):
                    code_words.append((y, code))
    if Counter(code for _, code in code_words) != Counter(code for row in rows for code in row["codes"]):
        raise ValueError("course codes in the PDF do not match the parsed rows")
    bands = [(top, bottom) for top, bottom in zip(edges, edges[1:])
             if any(top < y < bottom for y, _ in code_words)]
    if len(bands) != len(rows):
        raise ValueError("table rows could not be matched to their bands")
    def outside_table_row(item):
        y = (item["top"] + item["bottom"]) / 2
        return item["x1"] <= columns[0] or not any(top < y < bottom for top, bottom in bands)

    heading = " ".join(word["text"] for word in words if outside_table_row(word))
    # The official graduate heading has two editions of the same separator.
    heading = re.sub(r"(?<=Classes)\s*-\s*(?=20\d{2}\b)", "-", heading)
    notes = Counter(((row["kind"], tuple(row["codes"])), row["date"], row["periodText"], row["note"]) for row in rows
                    if row["note"] and not LOCAL_REVISION.fullmatch(normalize("NFKC", row["note"]).strip()))
    def text_color(char):
        color = char.get("non_stroking_color")
        return tuple(color) if isinstance(color, list) else color

    text_colors = Counter((char["text"], text_color(char)) for char in page.chars
                          if char["text"].strip() and outside_table_row(char))
    red_shapes = sorted(
        (rect["x0"], rect["top"], rect["x1"], rect["bottom"]) for rect in (*page.rects, *page.lines)
        if outside_table_row(rect) and
        (is_red(rect.get("non_stroking_color")) or is_red(rect.get("stroking_color")))
    )
    return heading, notes, text_colors, red_shapes


def comparable_page_geometry(before, after):
    def relative_crop(page):
        return tuple((value - origin) / scale for value, origin, scale in zip(
            page.cropbox, (page.bbox[0], page.bbox[1]) * 2, (page.width, page.height) * 2,
        ))

    # The school re-exports some pages at a proportional paper size.
    return (before.rotation == after.rotation
            and isclose(before.width / before.height, after.width / after.height, rel_tol=0.001)
            and all(isclose(x, y, abs_tol=0.001) for x, y in
                    zip(relative_crop(before), relative_crop(after))))


def page_scope(old, new, changed, date_range):
    changed_set = set(changed)
    for index, (before, after) in enumerate(zip(old.pages, new.pages)):
        try:
            old_context = page_context(before, date_range)
            if index not in changed_set:
                continue  # The page fingerprints already match.
            if not comparable_page_geometry(before, after) or before.images or after.images:
                return "document", f"page {index + 1}: page geometry or embedded images need review"
            if annotations(before) != annotations(after):
                return "document", f"page {index + 1}: annotations changed"
            if old_context != page_context(after, date_range):
                return "document", f"page {index + 1}: shared header, footnote or non-local note changed"
        except ValueError as error:
            return "document", f"page {index + 1}: {error}"
    return "pages", "table coverage checked and shared context matches"


def locate_pages(before_path, after_path, date_range):
    with pdfplumber.open(before_path) as before, pdfplumber.open(after_path) as after:
        if not before.pages or not after.pages:
            raise ValueError('timetable PDF has no pages')
        if len(before.pages) != len(after.pages):
            return 'document', 'page count changed', []
        old, new = page_fingerprints(before), page_fingerprints(after)
        changed = [index for index, (a, b) in enumerate(zip(old, new)) if a != b]
        if not changed:
            return 'none', 'page fingerprints match', []
        if {old[i] for i in changed} & {new[i] for i in changed}:
            return 'document', 'page order changed', [i + 1 for i in changed]
        scope, reason = page_scope(before, after, changed, date_range)
        return scope, reason, [i + 1 for i in changed]
