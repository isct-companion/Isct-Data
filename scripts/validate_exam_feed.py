#!/usr/bin/env python3
"""Validate exam-feed extraction hazards found in the official 2026 2Q PDF.

This is intentionally dependency-free and read-only. It catches PDF note text
leaking into English labels and truncated multi-room values before publication.
The LAS.B102 assertions are tied to the official page-16 rows and should be
updated only when a new official PDF is reviewed.
"""
import argparse
import json
import sys
from pathlib import Path


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("feed", type=Path)
    args = parser.parse_args()
    try:
        data = json.loads(args.feed.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"input error: {error}", file=sys.stderr)
        return 2

    errors = []
    entries = data.get("entries")
    if not isinstance(entries, list):
        errors.append("entries must be an array")
        entries = []
    ids = [entry.get("id") for entry in entries if isinstance(entry, dict)]
    if len(ids) != len(set(ids)):
        errors.append("duplicate entry id")

    by_code = {}
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append("entry is not an object")
            continue
        code = entry.get("courseCode")
        by_code[code] = entry
        english = entry.get("label", {}).get("en", "")
        lowered = english.lower()
        if any(marker in lowered for marker in ("confirm the room", "willtake", "please refer to lms")):
            errors.append(f"{code}: English label contains room-note text")
        room = entry.get("room")
        if isinstance(room, dict) and isinstance(room.get("ja"), str) and room["ja"].endswith("-"):
            errors.append(f"{code}: room value is truncated")
        rooms = entry.get("rooms")
        if rooms is not None:
            values = [item.get("ja") for item in rooms if isinstance(item, dict)]
            if not values or len(values) != len(set(values)) or any(not value for value in values):
                errors.append(f"{code}: invalid rooms array")

    for code, (title, rooms) in EXPECTED_LAS_B102.items():
        entry = by_code.get(code)
        if entry is None:
            errors.append(f"{code}: expected official page-16 row is missing")
            continue
        if entry.get("label", {}).get("en") != title:
            errors.append(f"{code}: English title differs from official page-16 title")
        actual = [item.get("ja") for item in entry.get("rooms", [])]
        if actual != rooms:
            errors.append(f"{code}: room list differs from official page-16 list")
        note = entry.get("notes", {}).get("en")
        if note != "Please refer to LMS to confirm the room you will take the exam.":
            errors.append(f"{code}: LMS room confirmation note is missing or changed")

    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"ok: {args.feed} ({len(entries)} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
