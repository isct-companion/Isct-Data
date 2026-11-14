#!/usr/bin/env python3
"""Validate published dataset contracts and subscription coverage."""
import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from dataset_contracts import DatasetContracts, InvalidContract, ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=ROOT, help="Directory containing the datasets and index.json")
    parser.add_argument("--format", choices=("text", "json"), default="text", help="Validation output format")
    parser.add_argument("--require-file", action="append", default=[], metavar="PATH",
                        help="Also require this dataset path to exist and be indexed. May be repeated.")
    args = parser.parse_args()
    try:
        count, issues = DatasetContracts().validate_repository(args.data_root, required_files=args.require_file)
    except InvalidContract as error:
        count, issues = 0, [error.issue]
    if args.format == "json":
        print(json.dumps({"schemaVersion": 1, "checked": count, "errors": [asdict(issue) for issue in issues]},
                         ensure_ascii=False))
    else:
        for issue in issues:
            print(issue, file=sys.stderr)
        print(f"Validated {count} datasets; {len(issues)} errors")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
