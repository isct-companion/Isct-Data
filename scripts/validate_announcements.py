#!/usr/bin/env python3
"""Validate the in-app announcements file the apps read directly (not through index.json)."""
import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
FILE = "announcements/v1/announcements.json"
SCHEMA = ROOT / "schema/announcements-v1.schema.json"
# An announcement is a notice, not a page: it always ends, and soon.
LONGEST = timedelta(days=90)
# A banner's title and body (UTF-8 bytes), short enough to stay a notice.
TITLE_BYTES, BODY_BYTES = 160, 2000
# The longest file the apps accept (Core's `announcements::LIMIT`).
FILE_BYTES = 256 * 1024
# Links open only on the school's and the app's own sites.
LINK_HOSTS = ("isct.ac.jp", "isctcomp.app")


def instant(raw):
    """The moment, or None for a date or offset no calendar has."""
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def version(raw):
    return tuple(int(part) for part in raw.split("."))


def allowed_link(url):
    """An https link to an allowed host, as the apps' URL parser reads it:
    no user name or password, and a port that is a port."""
    parts = urlsplit(url)
    try:
        parts.port
    except ValueError:
        return False
    if parts.username is not None or parts.password is not None:
        return False
    host = (parts.hostname or "").lower()
    return any(host == allowed or host.endswith("." + allowed) for allowed in LINK_HOSTS)


def issues(value):
    """Every problem with the file, as `pointer: message` lines."""
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    found = [f"/{'/'.join(map(str, error.absolute_path))}: {error.message}"
             for error in Draft202012Validator(schema).iter_errors(value)]
    if found:
        return found
    seen = set()
    for position, item in enumerate(value["announcements"]):
        at = f"/announcements/{position}"
        if item["id"] in seen:
            found.append(f"{at}/id: duplicate id {item['id']}")
        seen.add(item["id"])
        starts, expires = instant(item["startsAt"]), instant(item["expiresAt"])
        if starts is None or expires is None:
            for field, moment in (("startsAt", starts), ("expiresAt", expires)):
                if moment is None:
                    found.append(f"{at}/{field}: not a real date and time")
        elif expires <= starts:
            found.append(f"{at}/expiresAt: must be after startsAt")
        elif expires - starts > LONGEST:
            found.append(f"{at}/expiresAt: an announcement lasts at most {LONGEST.days} days")
        if "minAppVersion" in item and "maxAppVersion" in item \
                and version(item["minAppVersion"]) > version(item["maxAppVersion"]):
            found.append(f"{at}/maxAppVersion: must not be below minAppVersion")
        for field, limit in (("title", TITLE_BYTES), ("body", BODY_BYTES)):
            for language, text in item[field].items():
                if len(text.encode("utf-8")) > limit:
                    found.append(f"{at}/{field}/{language}: longer than {limit} bytes")
        if "link" in item and not allowed_link(item["link"]["url"]):
            found.append(f"{at}/link/url: host must be {' or '.join(LINK_HOSTS)} or a subdomain")
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=ROOT, help="Directory containing the announcements")
    args = parser.parse_args()
    path = args.data_root / FILE
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError) as error:
        print(f"{FILE}: {error}", file=sys.stderr)
        return 1
    if len(raw) > FILE_BYTES:
        print(f"{FILE}: longer than {FILE_BYTES} bytes, which the apps refuse", file=sys.stderr)
        return 1
    found = issues(value)
    for issue in found:
        print(f"{FILE}{issue}", file=sys.stderr)
    print(f"Validated {len(value.get('announcements', []))} announcements; {len(found)} errors")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
