#!/usr/bin/env python3
"""Compare two independent exam updates without sampling-time noise."""
import argparse
import json
import sys
from pathlib import Path

from validate_exam_feed import validate_feed


def records(root):
    rows = {}
    for path in sorted((root / "exam").glob("*/*.json")):
        feed = json.loads(path.read_text(encoding="utf-8"))
        errors = validate_feed(feed)
        if errors:
            raise ValueError(f"{path}: {'; '.join(errors)}")
        sources = {source["id"]: source["url"] for source in feed["source"]}
        for entry in feed["entries"]:
            key = (feed["academicYear"], path.parent.name, entry["quarter"], entry["id"])
            if key in rows:
                raise ValueError(f"duplicate scoped assessment: {key}")
            facts = {key: value for key, value in entry.items() if key != "sourceIds"}
            facts["sourceUrls"] = sorted({sources[source] for source in entry["sourceIds"]})
            rows[key] = facts
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        left, right = records(args.left), records(args.right)
        disagreements = []
        for key in sorted(left.keys() | right.keys()):
            if left.get(key) != right.get(key):
                disagreements.append({"assessment": list(key), "left": left.get(key), "right": right.get(key)})
        report = {
            "leftCount": len(left), "rightCount": len(right),
            "matchingCount": sum(left.get(key) == right.get(key) for key in left.keys() & right.keys()),
            "disagreements": disagreements,
            "scope": "assessment identity, exam facts, and source URLs; retrieval timestamps are excluded",
        }
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({key: value for key, value in report.items() if key != "disagreements"}, ensure_ascii=False))
        return 1 if disagreements else 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"exam comparison error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
