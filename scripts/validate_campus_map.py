#!/usr/bin/env python3
"""Validate the campus map export and its index entry (docs/campus-map-export.md).

The export is built in a private source repository and arrives here by pull request, so this is the only check it
gets before the App downloads it: schema, references, unique ids, coordinates, closed rings, sizes and index hash.
"""
import gzip
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

from jsonschema import Draft202012Validator

from dataset_rules import VERSIONED_INDEX

ROOT = Path(__file__).resolve().parent.parent
GROUP = "campusMap"
DIRECTORY = "campus-map"
MAX_JSON_BYTES = 16_000_000  # "decompressed must stay under 16 MB", read as decimal so either reading of MB holds
DIGITS = 7
# Generous boxes around each campus (about 300 m beyond its buildings): a point outside is in the wrong place.
CAMPUS_BOXES = {
    "ookayama": (139.674, 35.596, 139.690, 35.613),
    "suzukakedai": (139.476, 35.508, 139.492, 35.521),
}


def normalize_alias(text):
    """The format's alias normalisation: NFKC, every whitespace character removed, uppercase."""
    return re.sub(r"\s", "", unicodedata.normalize("NFKC", text)).upper()


def reject_constant(value):
    raise ValueError(f"non-finite JSON number: {value}")


def read_export(path):
    with gzip.open(path, "rb") as stream:
        raw = stream.read(MAX_JSON_BYTES)
        if stream.read(1):
            raise ValueError(f"decompressed size reaches the {MAX_JSON_BYTES}-byte limit")
    return json.loads(raw.decode("utf-8"), parse_constant=reject_constant)


def positions(value):
    if value and isinstance(value[0], (int, float)):
        yield value
    else:
        for item in value:
            yield from positions(item)


def rings(polygons):
    for polygon in polygons:
        yield from polygon


def check_content(doc, errors):
    """Everything the schema cannot say: references, unique ids, places, closed rings, the alias table."""
    ids = set()

    def claim(kind, ident):
        if ident in ids:
            errors.append(f"duplicate id {ident} ({kind})")
        ids.add(ident)

    buildings = {b["id"]: b for b in doc["buildings"]}
    level_campus, level_building = {}, {}
    shapes = []  # (where, campus, polygons) for ring checks
    points = []  # (where, campus, position)
    for b in doc["buildings"]:
        claim("building", b["id"])
        points.append((f"building {b['id']} center", b["campus"], b["center"]))
        shapes.append((f"building {b['id']} footprint", b["campus"], b["footprint"]))
        ordinals = [level["ordinal"] for level in b["levels"]]
        if ordinals != sorted(ordinals) or len(set(ordinals)) != len(ordinals):
            errors.append(f"building {b['id']}: levels are not sorted by distinct ordinal")
        if b["codes"] != sorted(b["codes"]):
            errors.append(f"building {b['id']}: codes are not sorted")
        for level in b["levels"]:
            claim("level", level["id"])
            level_campus[level["id"]], level_building[level["id"]] = b["campus"], b["id"]
            shapes.append((f"level {level['id']} outline", b["campus"], level["outline"]))
        own_levels = {level["id"] for level in b["levels"]}
        for entrance in b["entrances"]:
            claim("entrance", entrance["id"])
            points.append((f"entrance {entrance['id']}", b["campus"], entrance["point"]))
            if entrance["levelId"] is not None and entrance["levelId"] not in own_levels:
                errors.append(f"entrance {entrance['id']}: levelId is not a level of its building")

    rooms = {r["id"]: r for r in doc["rooms"]}
    for kind in ("units", "amenities", "rooms"):
        for item in doc[kind]:
            claim(kind, item["id"])
    linked = {}
    for unit in doc["units"]:
        campus = level_campus.get(unit["levelId"])
        if campus is None:
            errors.append(f"unit {unit['id']}: levelId does not resolve")
            continue
        points.append((f"unit {unit['id']} center", campus, unit["center"]))
        shapes.append((f"unit {unit['id']} polygon", campus, [unit["polygon"]]))
        if unit["roomId"] is not None:
            room = rooms.get(unit["roomId"])
            if room is None:
                errors.append(f"unit {unit['id']}: roomId does not resolve")
            elif unit["label"] != room["code"]:
                errors.append(f"unit {unit['id']}: label is not its room's code")
            linked[unit["id"]] = unit["roomId"]
    for amenity in doc["amenities"]:
        campus = level_campus.get(amenity["levelId"])
        if campus is None:
            errors.append(f"amenity {amenity['id']}: levelId does not resolve")
        else:
            points.append((f"amenity {amenity['id']}", campus, amenity["point"]))
    for n, work in enumerate(doc["linework"]):
        campus = level_campus.get(work["levelId"])
        if campus is None:
            errors.append(f"linework {n}: levelId does not resolve")
        else:
            points.extend((f"linework {n}", campus, p) for p in positions(work["lines"]))

    units = {unit["id"] for unit in doc["units"]}
    prefixes = {}
    for room in doc["rooms"]:
        if room["buildingId"] not in buildings:
            errors.append(f"room {room['id']}: buildingId does not resolve")
        prefixes.setdefault(room["buildingId"], set()).add(room["code"].rsplit("-", 1)[0])
        for unit in room["unitIds"]:
            if unit not in units:
                errors.append(f"room {room['id']}: unitId {unit} does not resolve")
            elif linked.get(unit) != room["id"]:
                errors.append(f"room {room['id']}: unit {unit} does not link back to it")
    for unit, room in linked.items():
        if room in rooms and unit not in rooms[room]["unitIds"]:
            errors.append(f"unit {unit}: its room does not list it")
    for b in doc["buildings"]:
        if b["codes"] != sorted(prefixes.get(b["id"], ())):
            errors.append(f"building {b['id']}: codes differ from its rooms' code prefixes")

    keys = list(doc["aliases"])
    if keys != sorted(keys):
        errors.append("aliases are not sorted")
    for key, targets in doc["aliases"].items():
        if normalize_alias(key) != key:
            errors.append(f"alias {key!r} is not in normalised form")
        errors.extend(f"alias {key!r}: {target} does not resolve" for target in targets if target not in rooms)
    for room in doc["rooms"]:
        if room["id"] not in doc["aliases"].get(normalize_alias(room["code"]), ()):
            errors.append(f"room {room['id']}: its code {room['code']!r} is not an alias of it")

    for where, campus, polygons in shapes:
        for ring in rings(polygons):
            if ring[0] != ring[-1]:
                errors.append(f"{where}: ring is not closed")
                break
        points.extend((where, campus, p) for p in positions(polygons))
    for where, campus, (lng, lat) in points:
        west, south, east, north = CAMPUS_BOXES[campus]
        if not (west <= lng <= east and south <= lat <= north):
            errors.append(f"{where}: [{lng}, {lat}] is outside the {campus} box")
        elif round(lng, DIGITS) != lng or round(lat, DIGITS) != lat:
            errors.append(f"{where}: [{lng}, {lat}] has more than {DIGITS} decimals")


def validate(root=ROOT):
    """(files checked, errors) for every export file and the campusMap index entries."""
    errors, count = [], 0
    pattern = VERSIONED_INDEX[GROUP]
    index = json.loads((root / "index.json").read_text(encoding="utf-8")).get(GROUP, {})
    present = sorted(p.relative_to(root).as_posix() for p in (root / DIRECTORY).rglob("*") if p.is_file()) \
        if (root / DIRECTORY).exists() else []
    expected = {pattern.format(version=version): version for version in index}
    for name in present:
        if name not in expected:
            errors.append(f"{name}: not a campusMap source in index.json (only {pattern} files belong here)")
    for name, version in sorted(expected.items()):
        path = root / name
        if not path.is_file():
            errors.append(f"index.json {GROUP} {version}: {name} does not exist")
            continue
        count += 1
        reference = index[version]
        if not isinstance(reference, dict) or reference.get("hash") != hashlib.sha256(path.read_bytes()).hexdigest():
            errors.append(f"index.json {GROUP} {version}: hash does not match {name}")
        schema_path = root / f"schema/campus-map-v{version}.schema.json"
        if not schema_path.exists():
            errors.append(f"{name}: no schema for format version {version}")
            continue
        try:
            doc = read_export(path)
        except (OSError, EOFError, ValueError) as error:
            errors.append(f"{name}: {error}")
            continue
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        found = [f"{name} {list(e.absolute_path)}: {e.message}" for e in Draft202012Validator(schema).iter_errors(doc)]
        if doc.get("formatVersion") != int(version):
            found.append(f"{name}: formatVersion is not {version}")
        errors.extend(found[:50])
        if not found:
            # The content checks assume the shape the schema guarantees.
            content = []
            check_content(doc, content)
            errors.extend(f"{name}: {message}" for message in content[:50])
            if len(content) > 50:
                errors.append(f"{name}: {len(content) - 50} more content errors")
    return count, errors


def main():
    count, errors = validate()
    for error in errors:
        print(error, file=sys.stderr)
    print(f"Validated {count} campus map exports; {len(errors)} errors")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
