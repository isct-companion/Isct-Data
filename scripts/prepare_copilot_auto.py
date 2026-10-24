#!/usr/bin/env python3
"""Preserve Copilot's native auto selector in the pinned gh-aw v0.93.2 harness."""
import argparse
import hashlib
from pathlib import Path
import sys

# v0.93.2 resolves auto through its generic alias map, selecting a fixed model
# unsupported by Student plans. AWF already passes native Copilot auto through.
# Keep the upstream harness and its security/usage/retry checks; alter only this
# resolver option, and refuse any upstream version we have not reviewed.
ORIGINAL_SHA256 = "ef6e2e1d5cab9d4f77fd70d2a203bc1eae8d4b17a83b9a401f8567e44108acec"
BEFORE = '      role: "main",\n      configuredModel,\n      aliasMap: aliasMap ??'
AFTER = '      role: "main",\n      configuredModel,\n      preserveAuto: true,\n      aliasMap: aliasMap ??'


def prepare(path):
    original = path.read_bytes()
    if hashlib.sha256(original).hexdigest() == ORIGINAL_SHA256:
        text = original.decode("utf-8")
        if text.count(BEFORE) != 1:
            raise ValueError("Copilot auto resolver target changed")
        path.write_text(text.replace(BEFORE, AFTER), encoding="utf-8")
        return
    text = original.decode("utf-8")
    if text.count(AFTER) == 1 and hashlib.sha256(text.replace(AFTER, BEFORE).encode()).hexdigest() == ORIGINAL_SHA256:
        return
    raise ValueError("Unreviewed gh-aw Copilot harness; review the native auto adapter before upgrading")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("actions_dir", type=Path)
    args = parser.parse_args()
    try:
        prepare(args.actions_dir / "copilot_harness.cjs")
        print("Preserved native Copilot auto selection (gh-aw v0.93.2)")
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
