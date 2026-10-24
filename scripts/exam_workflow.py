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


def run(root, year, quarter, level, candidate_path, timetable_pdf=None, retrieved_at=None):
    relative = f"exam/{level}/{year}-{quarter.lower()}.json"
    feed_path = scoped_path(relative, root)
    manifest_path = scoped_path(f"source-manifest/{year}-{quarter.lower()}.json", root)
    identities_path = scoped_path(f"review/exam-identities/{year}-{quarter.lower()}.json", root)
    review = load(scoped_path(candidate_path, root))
    if (review["academicYear"], review["quarter"], review["level"]) != (year, quarter, level):
        raise ValueError("candidate does not match the selected exam scope")
    before = load(feed_path)
    after = merge_candidates(before, review, level=level, manifest=load(manifest_path), identities=load(identities_path))
    class_relative, classes = None, None
    if timetable_pdf:
        from extract_exam_timetable import extract_classes
        class_relative = f"exam-week-classes/{level}/{year}-{quarter.lower()}.json"
        classes = extract_classes(scoped_path(timetable_pdf, root),
                                  calendar=load(scoped_path(f"academic-calendar/{year}.json", root)),
                                  quarter=quarter, level=level, manifest=load(manifest_path),
                                  exam_feed=after, retrieved_at=retrieved_at)
        errors = validate_feed(classes, root / "schema/exam-week-classes.schema.json")
        if errors:
            raise ValueError("; ".join(errors))
        # Use the exact PDF provenance for both feeds, even for a class-only revision.
        source = classes["source"][0]
        existing = next(s for s in after["source"] if s["id"] == source["id"])
        existing.update(source)
        class_path = root / class_relative
        if class_path.exists():
            previous_classes = load(class_path)
            comparable = copy.deepcopy(classes)
            for item in comparable["source"]:
                old = next((s for s in previous_classes["source"] if s["id"] == item["id"]), {})
                if "retrievedAt" in old:
                    item["retrievedAt"] = old["retrievedAt"]
            if comparable == previous_classes:
                classes = previous_classes
        previous_source = next(s for s in before["source"] if s["id"] == source["id"])
        if {k: v for k, v in existing.items() if k != "retrievedAt"} == {k: v for k, v in previous_source.items() if k != "retrievedAt"}:
            if "retrievedAt" in previous_source:
                existing["retrievedAt"] = previous_source["retrievedAt"]
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
    if classes is not None:
        references = updated["academicYears"][str(year)].setdefault("examWeekClasses", [])
        found = [ref for ref in references if ref["source"] == class_relative]
        if len(found) > 1:
            raise ValueError("duplicate exam-week class index reference")
        class_digest = canonical_hash(classes)
        if found:
            # Refuse to overwrite a class feed whose base has drifted.
            if found[0]["hash"] != canonical_hash(load(root / class_relative)):
                raise ValueError("base class feed does not match its index hash")
            if found[0]["hash"] != class_digest:
                found[0].update(hash=class_digest, ts=now)
        else:
            references.append({"source": class_relative, "hash": class_digest, "ts": now})
    feed_content = json.dumps(after, ensure_ascii=False, indent=2) + "\n"
    index_content = json.dumps(updated, ensure_ascii=False, indent=2) + "\n"
    if classes is not None:
        class_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(class_path, json.dumps(classes, ensure_ascii=False, indent=2) + "\n")
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
    patch = subprocess.check_output(["git", "diff", "--", relative, class_relative or relative, "index.json", "index.sha256"], cwd=root, text=True)
    atomic_write(out / "exams.patch", patch)
    return report


def acknowledge_sources(root, state_path, coverage_path):
    from check_exam_sources import STATE, allowed_url
    state = load(scoped_path(state_path, root))
    coverage = load(scoped_path(coverage_path, root))
    expected = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (root / "source-manifest").glob("*.json")}
    if state.get("schemaVersion") != 1 or state.get("manifests") != expected or not state.get("sources"):
        raise ValueError("source snapshot is missing or its manifests have changed")
    for url, digest in state["sources"].items():
        allowed_url(url)
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("invalid source snapshot hash")
    reviewed = {(s["manifest"], s["sourceId"]): s for s in coverage["sources"]}
    for manifest_path in expected:
        for source in load(root / manifest_path)["sources"]:
            item = reviewed.get((manifest_path, source["id"]), {})
            outcome = item.get("outcome")
            valid = {"reviewed", "not_yet_published", "different_scope"} if source["access"] == "public" else {"unavailable_no_lms_session"}
            if outcome not in valid:
                raise ValueError(f"incomplete source review: {manifest_path} {source['id']}")
            if source["access"] == "public" and (item.get("unresolvedFacts") != [] or not item.get("reviewedScope")):
                raise ValueError("public source scope is missing or has unresolved facts")
            if source["access"] == "public" and any(url not in state["sources"] for url in (source["url"], source.get("artifactUrl", source["url"]))):
                raise ValueError("source snapshot omits a manifest URL")
    if coverage.get("lmsDiscovery") != "unavailable_no_lms_session":
        raise ValueError("coverage must record the global LMS discovery gap")
    check_all(root)
    atomic_write(root / STATE, json.dumps(state, indent=2) + "\n")
    return {"sourceReview": "acknowledged", "sources": len(state["sources"])}


FEEDS = {
    "exam": "schema/exams.schema.json",
    "exam-week-classes": "schema/exam-week-classes.schema.json",
}


def check_all(root):
    count = 0
    for directory, schema in FEEDS.items():
        count += check_feeds(root, directory, root / schema)
    index = load(root / "index.json")
    for year, entry in index["academicYears"].items():
        for field, directory in (("exams", "exam"), ("examWeekClasses", "exam-week-classes")):
            listed = {reference["source"] for reference in entry.get(field, [])}
            present = {str(path.relative_to(root)) for path in (root / directory).glob(f"*/{year}-*.json")}
            if listed != present:
                raise ValueError(f"index {field} for {year} differs from {directory}/ files")
    generated = updated_index(root, copy.deepcopy(index), "2000-01-01T00:00:00Z")
    if generated != index:
        raise ValueError("dataset references contain stale hashes")
    index_bytes = (root / "index.json").read_bytes()
    if (root / "index.sha256").read_text().strip() != hashlib.sha256(index_bytes).hexdigest():
        raise ValueError("index.sha256 is stale")
    return {"examCount": count, "validation": "passed"}


def check_feeds(root, directory, schema):
    count = 0
    for path in sorted((root / directory).glob("*/*.json")):
        feed = load(path)
        if path.parent.name not in {"undergraduate", "graduate"}:
            raise ValueError(f"unknown exam level: {path}")
        if path.stem.split("-")[-1] not in {"1q", "2q", "3q", "4q"}:
            raise ValueError(f"unknown exam quarter: {path}")
        expected = f"{feed['academicYear']}-{path.stem.split('-')[-1]}"
        if path.stem != expected or any(entry["quarter"].lower() != path.stem.split('-')[-1] for entry in feed["entries"]):
            raise ValueError(f"exam filename/year/quarter mismatch: {path}")
        errors = validate_feed(feed, schema)
        if errors:
            raise ValueError("; ".join(errors))
        count += len(feed["entries"])
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int)
    parser.add_argument("--quarter", choices=("1Q", "2Q", "3Q", "4Q"))
    parser.add_argument("--level", choices=("undergraduate", "graduate"))
    parser.add_argument("--candidates", help="repository-relative agent candidate JSON")
    parser.add_argument("--timetable-pdf", help="repository-relative reviewed PDF; updates exam-week classes in the same operation")
    parser.add_argument("--retrieved-at", help="actual PDF retrieval time (RFC 3339)")
    parser.add_argument("--acknowledge-sources", help="repository-relative polled source snapshot, only after completing all reviews")
    parser.add_argument("--coverage", help="repository-relative coverage report for source acknowledgement")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        if args.check:
            result = check_all(ROOT)
        elif args.acknowledge_sources:
            if not args.coverage:
                parser.error("--acknowledge-sources requires --coverage")
            result = acknowledge_sources(ROOT, args.acknowledge_sources, args.coverage)
        else:
            if not all((args.year, args.quarter, args.level, args.candidates)):
                parser.error("apply requires --year, --quarter, --level and --candidates")
            result = run(ROOT, args.year, args.quarter, args.level, args.candidates, args.timetable_pdf, args.retrieved_at)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print(f"exam workflow error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
