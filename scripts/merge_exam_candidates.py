#!/usr/bin/env python3
"""Validate reviewed candidates, reconcile stable assessments, and update v1 feeds."""
import argparse
import copy
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from validate_exam_feed import ROOT, validate_feed, source_url_errors


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def merge_candidates(feed, review, *, level, manifest, identities):
    schema = json.loads((ROOT / "schema/exam-candidates.schema.json").read_text(encoding="utf-8"))
    errors = [error.message for error in Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(review)]
    errors.extend(validate_feed(feed))
    if errors:
        raise ValueError("; ".join(errors))
    year, quarter = review["academicYear"], review["quarter"]
    if review["level"] != level:
        raise ValueError("candidate level differs from destination level")
    if manifest.get("academicYear") != year or manifest.get("quarter") != quarter:
        raise ValueError("source manifest differs from candidate scope")
    if identities.get("academicYear") != year or identities.get("quarter") != quarter:
        raise ValueError("assessment identity registry differs from candidate scope")
    authorized = {source["id"]: source for source in manifest["sources"]}
    if len(authorized) != len(manifest["sources"]):
        raise ValueError("duplicate manifest source id")
    if feed["academicYear"] != year or any(entry["quarter"] != quarter for entry in feed["entries"]):
        raise ValueError("candidate year/quarter does not match the destination feed")
    for row in feed["entries"]:
        binding = identities["entries"].get(row["id"])
        if binding and (binding["level"] != level or binding["courseCode"] != row["courseCode"]):
            raise ValueError("destination feed differs from its registered level/course identity")
    result = copy.deepcopy(feed)
    sources = {source["id"]: source for source in result["source"]}
    review_sources = {source["id"]: source for source in review["sources"]}
    if len(review_sources) != len(review["sources"]):
        raise ValueError("duplicate candidate source id")
    seen = set()
    for candidate in review["candidates"]:
        if candidate.get("confirmed") is not True or candidate["assessmentKind"] != "final":
            continue
        code, assessment = candidate["courseCode"], candidate["assessmentId"]
        if candidate["quarter"] != quarter:
            raise ValueError(f"{code}: candidate quarter differs from review scope")
        if not code.strip() or code != code.strip() or any(ch.isspace() for ch in code):
            raise ValueError(f"{code}: require an exact course code including the class suffix")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", assessment):
            raise ValueError(f"{code}: assessmentId must be a stable identifier")
        identity = (code, assessment)
        if identity in seen:
            raise ValueError(f"{code}: duplicate assessment candidates; reconcile evidence first")
        seen.add(identity)
        evidence = candidate.get("evidenceText")
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError(f"{code}: reviewed evidenceText is required")
        if hashlib.sha256(evidence.encode()).hexdigest() != candidate.get("evidenceHash"):
            raise ValueError(f"{code}: evidenceHash does not match evidenceText")
        source_id = candidate["sourceId"]
        source = review_sources.get(source_id)
        if source is None:
            raise ValueError(f"{code}: reviewed source is missing")
        approved = authorized.get(source_id)
        if approved is None or approved.get("level") != level:
            raise ValueError(f"{code}: source is outside the exam manifest scope")
        if source["access"] != approved["access"] or source["scope"] != approved["scope"]:
            raise ValueError(f"{code}: candidate changes source access or coverage scope")
        approved_urls = {approved.get("url"), approved.get("artifactUrl")}
        if source["url"] not in approved_urls:
            raise ValueError(f"{code}: source URL differs from the manifest")
        if source.get("landingPageUrl") and source["landingPageUrl"] not in {approved.get("url"), approved.get("landingPageUrl")}:
            raise ValueError(f"{code}: landing page differs from the manifest")
        if not set(source["allowedFields"]).issubset(approved.get("allowedFields", [])):
            raise ValueError(f"{code}: candidate expands source publication fields")
        url_errors = source_url_errors(source)
        if url_errors:
            raise ValueError("; ".join(url_errors))
        previous_source = sources.get(source_id)
        if previous_source and previous_source["url"] != source["url"]:
            raise ValueError(f"{code}: source id cannot silently change URL")
        if source["level"] != level:
            raise ValueError(f"{code}: source level differs from candidate scope")
        public_source_fields = ("id", "title", "url", "landingPageUrl", "retrievedAt", "publishedAt", "sha256")
        incoming_source = {key: value for key, value in source.items() if key in public_source_fields}
        if previous_source:
            for field in ("retrievedAt", "publishedAt"):
                if field in previous_source and field in incoming_source:
                    previous_date = datetime.fromisoformat(previous_source[field].replace("Z", "+00:00"))
                    incoming_date = datetime.fromisoformat(incoming_source[field].replace("Z", "+00:00"))
                    if incoming_date < previous_date:
                        raise ValueError(f"{code}: older source provenance cannot overwrite newer provenance")
        sources[source_id] = {**(previous_source or {}), **incoming_source}
        if previous_source and incoming_source.get("retrievedAt") != previous_source.get("retrievedAt") and "sha256" not in incoming_source:
            sources[source_id].pop("sha256", None)
        emitted = {"courseCode", "quarter", "date", "room", "label", "sourceIds"}
        emitted.update(key for key in ("startTime", "endTime", "periods", "notes", "rooms", "syllabusCourseId", "classLabel", "sourcePages", "status") if key in candidate)
        if not emitted.issubset(candidate["publishFields"]):
            raise ValueError(f"{code}: publishFields does not permit all exam facts")
        if not emitted.issubset(source.get("allowedFields", [])):
            raise ValueError(f"{code}: source allowedFields does not permit all exam facts")
        stable_id = f"{year}-{quarter}-{level}-{code}-{assessment}"
        target = candidate.get("targetEntryId", stable_id)
        matches = [entry for entry in result["entries"] if entry["id"] == target]
        if "targetEntryId" in candidate and not matches:
            raise ValueError(f"{code}: targetEntryId does not exist")
        entry = matches[0] if matches else None
        if entry and target != stable_id:
            binding = identities["entries"].get(target)
            expected = {"level": level, "courseCode": code, "assessmentId": assessment}
            if binding != expected:
                raise ValueError(f"{code}: targetEntryId belongs to a different or unresolved assessment identity")
        if entry and (entry["courseCode"] != code or entry["quarter"] != quarter):
            raise ValueError(f"{code}: assessment target has a different course/quarter")
        if not entry:
            same_course = [row for row in result["entries"] if row["courseCode"] == code and row["quarter"] == quarter]
            if same_course and not candidate.get("newAssessment", False):
                raise ValueError(f"{code}: identify the existing assessment with targetEntryId or confirm newAssessment")
            if candidate.get("status") == "cancelled":
                raise ValueError(f"{code}: cancellation must identify a published assessment")
            entry = {"id": stable_id, "kind": "exam", "quarter": quarter, "courseCode": code, "status": "scheduled"}
            result["entries"].append(entry)
        entry.update({
            "date": candidate["date"], "room": candidate["room"], "label": candidate["label"],
            "sourceIds": sorted(set(entry.get("sourceIds", [])) | {source_id}),
            "status": candidate.get("status", entry.get("status", "scheduled")),
        })
        # Exact time and allocated periods are distinct; an update replaces old
        # timing evidence instead of retaining a stale period allocation.
        for field in ("startTime", "endTime", "periods"):
            entry.pop(field, None)
            if field in candidate:
                entry[field] = candidate[field]
        for field in ("notes", "rooms", "syllabusCourseId", "classLabel", "sourcePages"):
            if field in candidate:
                entry[field] = candidate[field]
    result["source"] = list(sources.values())
    if result != feed and review.get("baseFeedHash") != canonical_hash(feed):
        raise ValueError("candidate baseFeedHash is stale; reconcile against the current exam feed")
    errors = validate_feed(result)
    if errors:
        raise ValueError("; ".join(errors))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("feed", type=Path)
    parser.add_argument("candidates", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--identities", type=Path, required=True)
    parser.add_argument("--level", choices=("undergraduate", "graduate"), required=True)
    args = parser.parse_args()
    try:
        original = json.loads(args.feed.read_text(encoding="utf-8"))
        review = json.loads(args.candidates.read_text(encoding="utf-8"))
        if args.feed.parent.name in {"undergraduate", "graduate"} and args.feed.parent.name != args.level:
            raise ValueError("destination feed path differs from --level")
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        identities = json.loads(args.identities.read_text(encoding="utf-8"))
        merged = merge_candidates(original, review, level=args.level, manifest=manifest, identities=identities)
        args.output.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"merge error: {error}", file=sys.stderr)
        return 2
    print(f"ok: {args.output} ({len(merged['entries'])} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
