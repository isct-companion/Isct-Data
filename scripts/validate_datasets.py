#!/usr/bin/env python3
"""Validate every published dataset, including files not yet in the index."""
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS = {
    "academic-calendar": "academic-calendar",
    "departments": "departments",
    "important-dates": "important-dates",
    "class-schedules": "class-schedules",
    "exam": "exams",
    "exam-week-classes": "exam-week-classes",
}


def main():
    errors, count = [], 0
    for directory, name in SCHEMAS.items():
        schema = json.loads((ROOT / f"schema/{name}.schema.json").read_text())
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        paths = sorted((ROOT / directory).rglob("*.json"))
        if not paths:
            errors.append(f"{directory}: no datasets found")
        for path in paths:
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                errors.extend(f"{path.relative_to(ROOT)} {list(e.absolute_path)}: {e.message}"
                              for e in validator.iter_errors(value))
            except (OSError, ValueError) as error:
                errors.append(f"{path}: {error}")
            count += 1
    for error in errors:
        print(error, file=sys.stderr)
    print(f"Validated {count} datasets; {len(errors)} errors")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
