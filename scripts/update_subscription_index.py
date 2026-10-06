#!/usr/bin/env python3
"""Add dataset hashes/timestamps to index.json and write index.sha256.

The script uses only Python's standard library. Existing timestamps are kept
when a dataset's canonical JSON hash is unchanged, so repeated runs are stable.
"""

import argparse
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SHA256 = re.compile(r"[0-9a-f]{64}")
RFC3339 = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})"
)


def reject_constant(value):
    raise ValueError(f"non-finite JSON number is not supported: {value}")


def normalize(value):
    if isinstance(value, dict):
        return {key: normalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize(item) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite JSON number is not supported")
        if value.is_integer():
            return int(value)
    return value


def canonical_json_hash(path):
    value = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)
    canonical = json.dumps(
        normalize(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def validate_timestamp(value):
    if not isinstance(value, str) or not RFC3339.fullmatch(value):
        raise ValueError(f"timestamp is not RFC 3339: {value!r}")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp has no timezone: {value!r}")
    return value


def source_path(root, source):
    if not isinstance(source, str) or not source or "\\" in source:
        raise ValueError(f"invalid dataset source: {source!r}")
    candidate = (root / source).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"dataset source leaves repository: {source}") from error
    if not candidate.is_file():
        raise ValueError(f"dataset source does not exist: {source}")
    return candidate


def update_reference(root, reference, timestamp):
    if isinstance(reference, str):
        source = reference
        previous_hash = None
        previous_timestamp = None
    elif isinstance(reference, dict):
        if set(reference) != {"source", "hash", "ts"}:
            raise ValueError("dataset references must contain only source, hash, and ts")
        source = reference["source"]
        previous_hash = reference["hash"]
        previous_timestamp = validate_timestamp(reference["ts"])
        if not isinstance(previous_hash, str) or not SHA256.fullmatch(previous_hash):
            raise ValueError(f"invalid dataset hash: {previous_hash!r}")
    else:
        raise ValueError(f"invalid dataset reference: {reference!r}")

    digest = canonical_json_hash(source_path(root, source))
    return {
        "source": source,
        "hash": digest,
        "ts": previous_timestamp if previous_hash == digest else timestamp,
    }


def updated_index(root, index, timestamp):
    allowed_root = {"academicYears", "admissionYears"}
    if set(index) != allowed_root:
        raise ValueError("index.json must contain academicYears and admissionYears only")
    if not isinstance(index["academicYears"], dict) or not isinstance(
        index["admissionYears"], dict
    ):
        raise ValueError("academicYears and admissionYears must be objects")

    for entry in index["academicYears"].values():
        allowed = {"academicCalendar", "importantDates", "exams"}
        if not isinstance(entry, dict) or not set(entry).issubset(allowed):
            raise ValueError("invalid academic-year index entry")
        if "academicCalendar" in entry:
            entry["academicCalendar"] = update_reference(
                root, entry["academicCalendar"], timestamp
            )
        if "importantDates" in entry:
            entry["importantDates"] = update_reference(
                root, entry["importantDates"], timestamp
            )
        if "exams" in entry:
            if not isinstance(entry["exams"], list):
                raise ValueError("exams must be an array")
            entry["exams"] = [
                update_reference(root, reference, timestamp)
                for reference in entry["exams"]
            ]

    for entry in index["admissionYears"].values():
        if not isinstance(entry, dict) or set(entry) != {"departments"}:
            raise ValueError("invalid admission-year index entry")
        entry["departments"] = update_reference(root, entry["departments"], timestamp)
    return index


def atomic_write(path, content):
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            output.write(content)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Repository root containing index.json (default: script parent)",
    )
    parser.add_argument(
        "--timestamp",
        help="RFC 3339 timestamp for changed sources; defaults to current UTC",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 instead of writing when index.json or index.sha256 is stale",
    )
    args = parser.parse_args()
    root = args.data_root.resolve()
    index_path = root / "index.json"
    hash_path = root / "index.sha256"
    timestamp = args.timestamp or datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")
    try:
        validate_timestamp(timestamp)
        index = json.loads(
            index_path.read_text(encoding="utf-8"), parse_constant=reject_constant
        )
        updated = updated_index(root, index, timestamp)
        index_content = json.dumps(updated, ensure_ascii=False, indent=2) + "\n"
        index_digest = hashlib.sha256(index_content.encode("utf-8")).hexdigest()
        hash_content = index_digest + "\n"
        current_index = index_path.read_text(encoding="utf-8")
        current_hash = hash_path.read_text(encoding="utf-8") if hash_path.exists() else ""
        stale = current_index != index_content or current_hash != hash_content
        if args.check:
            if stale:
                print("subscription index is stale", file=sys.stderr)
                return 1
            print(index_digest)
            return 0
        if stale:
            atomic_write(index_path, index_content)
            atomic_write(hash_path, hash_content)
        print(index_digest)
        return 0
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
