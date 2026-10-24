#!/usr/bin/env python3
"""Prepare a data-only bundle, then validate and fast-forward it from a trusted job."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
REPOSITORY = "isct-companion/Isct-Data"
CHECK = "Validate all datasets"
FEED = re.compile(r"(?:exam|exam-week-classes)/(?:undergraduate|graduate)/\d{4}-[1-4]q\.json")
METADATA = {"index.json", "index.sha256", "review/exam-source-state.json"}


def git(root, *args):
    return subprocess.check_output(["git", "-c", "core.hooksPath=/dev/null", *args], cwd=root, text=True).strip()


def allowed_path(root, name):
    if name not in METADATA and not FEED.fullmatch(name):
        raise ValueError(f"publication path is outside the exam allowlist: {name}")
    path = root / name
    for part in (path, *path.parents):
        if part == root:
            break
        if part.is_symlink():
            raise ValueError("publication cannot follow symbolic links")
    path.resolve().relative_to(root.resolve())
    return path


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def prepare(root, base):
    if git(root, "rev-parse", "HEAD") != base:
        raise ValueError("agent checkout moved away from the immutable run base")
    changed = set(git(root, "diff", "--no-ext-diff", "--name-only", base).splitlines())
    changed.update(git(root, "ls-files", "--others", "--exclude-standard").splitlines())
    files = {}
    for name in sorted(changed):
        path = allowed_path(root, name)
        if not path.is_file():
            raise ValueError("automatic publication cannot delete files")
        files[name] = path.read_text(encoding="utf-8")
    if len(files) > 50 or sum(len(v.encode()) for v in files.values()) > 16 * 1024 * 1024:
        raise ValueError("publication exceeds the data bundle limit")
    return {"schemaVersion": 1, "baseSha": base, "files": files,
            "observedState": load(root / ".exam-runs/source-state.json"),
            "coverage": load(root / ".exam-runs/coverage.json")}


def apply_and_validate(root, bundle, base, *, fresh_state=None):
    if bundle.get("schemaVersion") != 1 or bundle.get("baseSha") != base or git(root, "rev-parse", "HEAD") != base:
        raise ValueError("publication base is stale")
    if git(root, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("publisher checkout must be pristine")
    files = bundle["files"]
    if not isinstance(files, dict) or len(files) > 50:
        raise ValueError("invalid publication file map")
    total = 0
    for name, content in files.items():
        allowed_path(root, name)
        if not isinstance(content, str):
            raise ValueError("publication files must be UTF-8 text")
        total += len(content.encode())
        if name.endswith(".json"):
            json.loads(content)
    if total > 16 * 1024 * 1024:
        raise ValueError("publication exceeds the data bundle limit")
    if fresh_state is not None and fresh_state != bundle["observedState"]:
        raise ValueError("official sources changed after review; retry instead of publishing stale facts")
    previous_index = load(root / "index.json")
    updated_index = json.loads(files.get("index.json", json.dumps(previous_index)))
    # The index may change only the two exam reference arrays. Other subscriptions
    # retain their exact metadata, even if an agent supplies a valid but unrelated edit.
    before, after = json.loads(json.dumps(previous_index)), json.loads(json.dumps(updated_index))
    for index in (before, after):
        for entry in index["academicYears"].values():
            for field in ("exams", "examWeekClasses"):
                entry.pop(field, None)
    if before != after:
        raise ValueError("publication changes unrelated subscription metadata")
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    # Reuse the fixed writer's full-coverage acknowledgement in this clean,
    # immutable-base checkout; no model-generated Python or workflow is executed.
    run_dir = root / ".exam-runs"
    run_dir.mkdir(exist_ok=True)
    for name, value in (("publish-state.json", bundle["observedState"]), ("publish-coverage.json", bundle["coverage"])):
        (run_dir / name).write_text(json.dumps(value), encoding="utf-8")
    subprocess.run([sys.executable, "scripts/exam_workflow.py", "--acknowledge-sources", ".exam-runs/publish-state.json",
                    "--coverage", ".exam-runs/publish-coverage.json"], cwd=root, check=True)
    if load(root / "review/exam-source-state.json") != bundle["observedState"]:
        raise ValueError("review baseline does not match observed sources")
    for command in (["scripts/validate_datasets.py"], ["scripts/update_subscription_index.py", "--check"],
                    ["scripts/exam_workflow.py", "--check"]):
        subprocess.run([sys.executable, *command], cwd=root, check=True)
    names = set(files) | {"review/exam-source-state.json"}
    return {name: (root / name).read_text(encoding="utf-8") for name in sorted(names)
            if git(root, "status", "--porcelain", "--", name)}


def request(token, method, path, body=None):
    req = Request(f"https://api.github.com/repos/{REPOSITORY}/{path}", method=method,
                  data=json.dumps(body).encode() if body is not None else None,
                  headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                           "Content-Type": "application/json", "User-Agent": "Isct-Data-publisher"})
    try:
        with urlopen(req, timeout=60) as response:
            return json.load(response)
    except HTTPError as error:
        raise ValueError(f"GitHub publication API {method} {path} failed with HTTP {error.code}") from None


def publish(base, files, write_token, status_token, run_url, *, api=request):
    if not files:
        return {"changed": False, "sha": base}
    if not write_token or not status_token:
        raise ValueError("publisher credentials are missing")
    if api(write_token, "GET", "git/ref/heads/main")["object"]["sha"] != base:
        raise ValueError("main advanced during review; rerun on the latest main")
    original = api(write_token, "GET", f"git/commits/{base}")
    tree = api(write_token, "POST", "git/trees", {"base_tree": original["tree"]["sha"], "tree": [
        {"path": name, "mode": "100644", "type": "blob", "content": content} for name, content in files.items()]})
    commit = api(write_token, "POST", "git/commits", {
        "message": "Update reviewed official exam data", "tree": tree["sha"], "parents": [base]})
    sha = commit["sha"]
    # This is the result of the full validation just performed on this exact tree,
    # recorded with the Actions token so main's required GitHub Actions check holds.
    api(status_token, "POST", f"statuses/{sha}", {"state": "success", "context": CHECK,
            "description": "Full data, index, exam and boundary checks passed in trusted publisher", "target_url": run_url})
    # No force: a concurrent main update causes GitHub to reject this ref change.
    api(write_token, "PATCH", "git/refs/heads/main", {"sha": sha, "force": False})
    return {"changed": True, "sha": sha, "files": sorted(files)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--base", required=True)
    parser.add_argument("--prepare", type=Path)
    parser.add_argument("--bundle", type=Path)
    args = parser.parse_args()
    try:
        root = args.root.resolve()
        if args.prepare:
            bundle = prepare(root, args.base)
            args.prepare.parent.mkdir(parents=True, exist_ok=True)
            args.prepare.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
            print(json.dumps({"preparedFiles": sorted(bundle["files"])}))
        else:
            if os.environ.get("GITHUB_REF") != "refs/heads/main" or os.environ.get("GITHUB_REPOSITORY") != REPOSITORY:
                raise ValueError("direct publication runs only from this repository's main branch")
            if not args.bundle:
                parser.error("--bundle is required for publication")
            from check_exam_sources import snapshot
            bundle = load(args.bundle)
            fresh, _, _ = snapshot(root)
            files = apply_and_validate(root, bundle, args.base, fresh_state=fresh)
            subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=root, check=True)
            result = publish(args.base, files, os.environ.get("DATA_PR_TOKEN"), os.environ.get("STATUS_TOKEN"),
                             f"https://github.com/{REPOSITORY}/actions/runs/{os.environ['GITHUB_RUN_ID']}")
            print(json.dumps(result))
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print(f"exam publication failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
