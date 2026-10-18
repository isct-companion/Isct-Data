#!/usr/bin/env python3
"""Exam-only write boundary shared by local agents and GitHub Actions."""
import argparse
import copy
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from merge_exam_candidates import canonical_hash, merge_candidates
from update_subscription_index import atomic_write, updated_index
from validate_exam_feed import ROOT, validate_feed


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def scoped_path(raw, root):
    path = (root / raw).resolve()
    path.relative_to(root.resolve())
    if not path.is_file():
        raise ValueError(f"missing repository input: {raw}")
    return path


def run(root, year, quarter, level, candidate_path):
    relative = f"exam/{level}/{year}-{quarter.lower()}.json"
    feed_path = scoped_path(relative, root)
    manifest_path = scoped_path(f"source-manifest/{year}-{quarter.lower()}.json", root)
    identities_path = scoped_path(f"review/exam-identities/{year}-{quarter.lower()}.json", root)
    review = load(scoped_path(candidate_path, root))
    if (review["academicYear"], review["quarter"], review["level"]) != (year, quarter, level):
        raise ValueError("candidate does not match the selected exam scope")
    before = load(feed_path)
    after = merge_candidates(before, review, level=level, manifest=load(manifest_path), identities=load(identities_path))
    index_path = root / "index.json"
    index = load(index_path)
    references = index["academicYears"][str(year)]["exams"]
    matches = [ref for ref in references if ref["source"] == relative]
    if len(matches) != 1:
        raise ValueError("selected exam feed must have exactly one index reference")
    expected_before = canonical_hash(before)
    if matches[0]["hash"] != expected_before:
        raise ValueError("base exam feed does not match its index hash")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    updated = copy.deepcopy(index)
    ref = next(ref for ref in updated["academicYears"][str(year)]["exams"] if ref["source"] == relative)
    digest = canonical_hash(after)
    if digest != ref["hash"]:
        ref.update(hash=digest, ts=now)
    # Compute all changes before writing. Only one exam reference may change.
    check = copy.deepcopy(updated)
    next(ref for ref in check["academicYears"][str(year)]["exams"] if ref["source"] == relative).update(matches[0])
    if check != index:
        raise ValueError("exam update attempted to change unrelated index metadata")
    feed_content = json.dumps(after, ensure_ascii=False, indent=2) + "\n"
    index_content = json.dumps(updated, ensure_ascii=False, indent=2) + "\n"
    atomic_write(feed_path, feed_content)
    atomic_write(index_path, index_content)
    atomic_write(root / "index.sha256", hashlib.sha256(index_content.encode()).hexdigest() + "\n")
    report = {
        "scope": {"academicYear": year, "quarter": quarter, "level": level},
        "feed": relative, "beforeCount": len(before["entries"]), "afterCount": len(after["entries"]),
        "baseHash": expected_before, "resultHash": digest,
        "changed": before != after, "candidateFile": candidate_path,
    }
    out = root / ".exam-runs"
    out.mkdir(exist_ok=True)
    atomic_write(out / "result.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    patch = subprocess.check_output(["git", "diff", "--", relative, "index.json", "index.sha256"], cwd=root, text=True)
    atomic_write(out / "exams.patch", patch)
    return report


def check_all(root):
    count = 0
    for path in sorted((root / "exam").glob("*/*.json")):
        feed = load(path)
        if path.parent.name not in {"undergraduate", "graduate"}:
            raise ValueError(f"unknown exam level: {path}")
        if path.stem.split("-")[-1] not in {"1q", "2q", "3q", "4q"}:
            raise ValueError(f"unknown exam quarter: {path}")
        expected = f"{feed['academicYear']}-{path.stem.split('-')[-1]}"
        if path.stem != expected or any(entry["quarter"].lower() != path.stem.split('-')[-1] for entry in feed["entries"]):
            raise ValueError(f"exam filename/year/quarter mismatch: {path}")
        errors = validate_feed(feed)
        if errors:
            raise ValueError("; ".join(errors))
        count += len(feed["entries"])
    index = load(root / "index.json")
    generated = updated_index(root, copy.deepcopy(index), "2000-01-01T00:00:00Z")
    if generated != index:
        raise ValueError("dataset references contain stale hashes")
    index_bytes = (root / "index.json").read_bytes()
    if (root / "index.sha256").read_text().strip() != hashlib.sha256(index_bytes).hexdigest():
        raise ValueError("index.sha256 is stale")
    return {"examCount": count, "validation": "passed"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int)
    parser.add_argument("--quarter", choices=("1Q", "2Q", "3Q", "4Q"))
    parser.add_argument("--level", choices=("undergraduate", "graduate"))
    parser.add_argument("--candidates", help="repository-relative agent candidate JSON")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        if args.check:
            result = check_all(ROOT)
        else:
            if not all((args.year, args.quarter, args.level, args.candidates)):
                parser.error("apply requires --year, --quarter, --level and --candidates")
            result = run(ROOT, args.year, args.quarter, args.level, args.candidates)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print(f"exam workflow error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
