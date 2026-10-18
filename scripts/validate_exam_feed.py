#!/usr/bin/env python3
"""Validate the shared v1 exam contract and source relationships."""
import argparse
import json
import sys
from datetime import date
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent.parent

EXPECTED_LAS_B102 = {
    "LAS.B102-01": ("Fundamental Life Science 1-2 A", [
        "M-B07", "M-178", "M-124", "M-278", "M-374", "W2-401",
        "WL2-201", "WL2-301", "WL2-401", "W8E-101",
    ]),
    "LAS.B102-02": ("Fundamental Life Science 1-2 B", [
        "M-B07", "M-178", "M-124", "M-278", "M-374", "W2-401",
        "WL2-201", "WL2-301", "WL2-401", "W8E-101",
    ]),
    "LAS.B102-03": ("Fundamental Life Science 1-2 C", [
        "M-B07", "M-178", "M-124", "M-278", "M-374", "W2-401",
        "WL2-201", "WL2-301", "WL2-401", "W8E-101",
    ]),
    "LAS.B102-04": ("Fundamental Life Science 1-2 D", [
        "M-B07", "M-178", "M-124", "M-278", "M-374", "W2-401",
        "WL2-201", "WL2-301", "WL2-401", "W8E-101",
    ]),
    "LAS.B102-05": ("Fundamental Life Science 1-2 E", [
        "M-B07", "M-178", "M-124", "M-278", "M-374", "W2-401",
        "WL2-201", "WL2-301", "WL2-401", "W8E-101",
    ]),
    "LAS.B102-06": ("Fundamental Life Science 1-2 F", [
        "M-B07", "M-178", "M-124", "M-278", "M-374", "W2-401",
        "WL2-201", "WL2-301", "WL2-401", "W8E-101",
    ]),
    "LAS.B102-07": ("Fundamental Life Science 1-2 G", [
        "M-B07", "M-178", "M-124", "M-278", "M-374", "W2-401",
        "WL2-201", "WL2-301", "WL2-401", "W8E-101",
    ]),
    "LAS.B102-08": ("Fundamental Life Science 1-2 H", [
        "M-B07", "M-178", "M-124", "M-278", "M-374", "W2-401",
        "WL2-201", "WL2-301", "WL2-401", "W8E-101",
    ]),
}


def source_url_errors(source):
    errors = []
    session_keys = {"sesskey", "session", "sessionid", "token", "access_token", "password", "passcode", "auth", "authorization", "x-amz-signature"}
    for field in ("url", "landingPageUrl"):
        if field not in source:
            continue
        parsed = urlsplit(source[field])
        if parsed.username or parsed.password or any(key.lower() in session_keys for key, _ in parse_qsl(parsed.query)):
            errors.append(f"{source['id']}: {field} contains authentication/session state")
    return errors


def validate_feed(data, schema_path=None, check_las_b102=False):
    """Return publication errors; schema checks guard the relational checks."""
    schema = json.loads((schema_path or ROOT / "schema/exams.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = [
        f"schema at {list(error.absolute_path)}: {error.message}"
        for error in validator.iter_errors(data)
    ]
    if errors:
        return errors
    for source in data["source"]:
        errors.extend(source_url_errors(source))
    year = data["academicYear"]
    source_ids = [source["id"] for source in data["source"]]
    if len(source_ids) != len(set(source_ids)):
        errors.append("duplicate source id")
    ids = [entry["id"] for entry in data["entries"]]
    if len(ids) != len(set(ids)):
        errors.append("duplicate entry id")
    for entry in data["entries"]:
        identity = entry["id"]
        when = date.fromisoformat(entry["date"])
        if not date(year, 4, 1) <= when < date(year + 1, 4, 1):
            errors.append(f"{identity}: date is outside academicYear")
        if not set(entry["sourceIds"]).issubset(source_ids):
            errors.append(f"{identity}: sourceIds reference undeclared sources")
        periods = entry.get("periods")
        if periods and periods[0] > periods[1]:
            errors.append(f"{identity}: first period must not exceed last period")
        if "startTime" in entry and entry["startTime"] >= entry["endTime"]:
            errors.append(f"{identity}: startTime must precede endTime")
        lowered = entry["label"].get("en", "").lower()
        if any(marker in lowered for marker in ("confirm the room", "willtake", "please refer to lms")):
            errors.append(f"{identity}: English title contains room instructions")
        room = entry["room"]
        if room and room["ja"].endswith("-"):
            errors.append(f"{identity}: room value is truncated")
        if "rooms" in entry:
            rooms = [room["ja"] for room in entry["rooms"]]
            if len(rooms) != len(set(rooms)):
                errors.append(f"{identity}: duplicate room")
    if check_las_b102:
        if year != 2026 or any(entry["quarter"] != "2Q" for entry in data["entries"]):
            errors.append("LAS.B102 regression applies only to 2026 2Q undergraduate data")
        by_code = {entry["courseCode"]: entry for entry in data["entries"]}
        for code, (title, rooms) in EXPECTED_LAS_B102.items():
            entry = by_code.get(code)
            if entry is None:
                errors.append(f"{code}: reviewed page-16 row is missing")
                continue
            if entry["label"].get("en") != title:
                errors.append(f"{code}: English title differs from reviewed source")
            if [room["ja"] for room in entry.get("rooms", [])] != rooms:
                errors.append(f"{code}: rooms differ from reviewed source")
            if entry.get("notes", {}).get("en") != "Please refer to LMS to confirm the room you will take the exam.":
                errors.append(f"{code}: room confirmation note differs from reviewed source")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("feed", type=Path)
    parser.add_argument("--schema", type=Path)
    parser.add_argument("--check-las-b102", action="store_true", help="check the reviewed 2026 2Q undergraduate PDF rows")
    args = parser.parse_args()
    try:
        data = json.loads(args.feed.read_text(encoding="utf-8"))
        errors = validate_feed(data, args.schema, args.check_las_b102)
    except (OSError, ValueError) as error:
        print(f"input error: {error}", file=sys.stderr)
        return 2
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"ok: {args.feed} ({len(data['entries'])} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
