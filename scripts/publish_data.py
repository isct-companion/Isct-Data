#!/usr/bin/env python3
"""Prepare a data-only bundle, then validate and fast-forward it from a trusted job."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from dataset_rules import DATASETS, allowed_path as scoped_allowed_path, assert_public_provenance, feed_path, manual_exam_facts, state_path

ROOT = Path(__file__).resolve().parent.parent
REPOSITORY = "isct-companion/Isct-Data"
CHECK = "Validate all datasets"


def git(root, *args):
    return subprocess.check_output(["git", "-c", "core.hooksPath=/dev/null", *args], cwd=root, text=True).strip()


def allowed_path(root, name, dataset='exams'):
    return scoped_allowed_path(root, name, dataset)


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def prepare(root, base, dataset='exams'):
    if git(root, "rev-parse", "HEAD") != base:
        raise ValueError("agent checkout moved away from the immutable run base")
    changed = set(git(root, "diff", "--no-ext-diff", "--name-only", base).splitlines())
    changed.update(git(root, "ls-files", "--others", "--exclude-standard").splitlines())
    files = {}
    for name in sorted(changed):
        path = allowed_path(root, name, dataset)
        if not path.is_file():
            raise ValueError("automatic publication cannot delete files")
        files[name] = path.read_text(encoding="utf-8")
    if len(files) > 50 or sum(len(v.encode()) for v in files.values()) > 16 * 1024 * 1024:
        raise ValueError("publication exceeds the data bundle limit")
    run_dir = root / '.data-runs'
    modern = (run_dir / 'review.json').exists()
    coverage = load(root / '.exam-runs/coverage.json') if dataset == 'exams' else load(run_dir / 'review.json')
    return {'schemaVersion': 2 if modern else 1, 'dataset': dataset, 'baseSha': base, 'files': files,
            'observedState': load((run_dir if modern else root / '.exam-runs') / 'source-state.json'),
            'coverage': coverage, 'review': load(run_dir / 'review.json') if modern else None}


def apply_and_validate(root, bundle, base, *, fresh_state=None, dataset='exams'):
    if bundle.get("schemaVersion") not in (1, 2) or bundle.get("dataset", "exams") != dataset or bundle.get("baseSha") != base or git(root, "rev-parse", "HEAD") != base:
        raise ValueError("publication base is stale")
    if git(root, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("publisher checkout must be pristine")
    files = bundle["files"]
    if not isinstance(files, dict) or len(files) > 50:
        raise ValueError("invalid publication file map")
    total = 0
    for name, content in files.items():
        allowed_path(root, name, dataset)
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
    # Only this dataset's reference fields may change. Other subscriptions
    # retain their exact metadata, even if an agent supplies a valid but unrelated edit.
    before, after = json.loads(json.dumps(previous_index)), json.loads(json.dumps(updated_index))
    group, fields = DATASETS[dataset]['index']
    for index in (before, after):
        for year in list(index[group]):
            for field in fields:
                index[group][year].pop(field, None)
            if not index[group][year]:
                del index[group][year]
    if before != after:
        raise ValueError('publication changes unrelated subscription metadata')
    if dataset == 'exams':
        for name, content in files.items():
            if name.startswith('exam/'):
                original = load(root / name) if (root / name).exists() else {'source': [], 'entries': []}
                if manual_exam_facts(root, original) != manual_exam_facts(root, json.loads(content)):
                    raise ValueError('automation cannot modify manually maintained exam facts')
    for name, content in files.items():
        if feed_path(name, dataset):
            assert_public_provenance(root, name, json.loads(content), bundle['observedState'], dataset)
    if bundle.get('review') is not None:
        if bundle['review'].get('dataset') != dataset:
            raise ValueError('review dataset differs from the fixed publication scope')
        from data_workflow import validate_coverage
        validate_coverage(bundle['observedState'], bundle['review'])
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    # A clean base supplies all executable code; the model supplies data only.
    if dataset == 'exams':
        run_dir = root / '.exam-runs'
        run_dir.mkdir(exist_ok=True)
        for name, value in (('publish-state.json', bundle['observedState']), ('publish-coverage.json', bundle['coverage'])):
            (run_dir / name).write_text(json.dumps(value), encoding='utf-8')
        subprocess.run([sys.executable, 'scripts/exam_workflow.py', '--acknowledge-sources', '.exam-runs/publish-state.json',
                        '--coverage', '.exam-runs/publish-coverage.json'], cwd=root, check=True)
    else:
        state_file = root / state_path(dataset); state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps(bundle['observedState'], indent=2) + '\n', encoding='utf-8')
    if load(root / state_path(dataset)) != bundle['observedState']:
        raise ValueError('review baseline differs from observed sources')
    for command in (["scripts/validate_datasets.py"], ["scripts/update_subscription_index.py", "--check"],
                    ["scripts/exam_workflow.py", "--check"]):
        subprocess.run([sys.executable, *command], cwd=root, check=True)
    names = set(files) | {state_path(dataset)}
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


def publish(base, files, write_token, status_token, run_url, *, api=request, dataset='exams'):
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
        "message": f"Update reviewed public {dataset} data", "tree": tree["sha"], "parents": [base]})
    sha = commit["sha"]
    # This is the result of the full validation just performed on this exact tree,
    # recorded with the Actions token so main's required GitHub Actions check holds.
    api(status_token, "POST", f"statuses/{sha}", {"state": "success", "context": CHECK,
            "description": "Full data, index, exam and boundary checks passed in trusted publisher", "target_url": run_url})
    # No force: a concurrent main update causes GitHub to reject this ref change.
    api(write_token, "PATCH", "git/refs/heads/main", {"sha": sha, "force": False})
    return {"changed": True, "sha": sha, "files": sorted(files)}


def verify_public_exam_artifacts(root, documents):
    import hashlib
    import re
    import tempfile
    import pdfplumber
    from extract_exam_timetable import extract_classes
    for manifest_path in (root / 'source-manifest').glob('*.json'):
        manifest = load(manifest_path)
        for source in manifest['sources']:
            if source['access'] != 'public':
                continue
            content = documents[source['artifactUrl']]
            with tempfile.NamedTemporaryFile(suffix='.pdf') as temporary:
                temporary.write(content); temporary.flush()
                with pdfplumber.open(temporary.name) as pdf:
                    heading = (pdf.pages[0].extract_text() or '')[:500]
                actual = re.search(r'Schedule of Final Exams(?: and Classes)?\s*-\s*(\d{4})\s+([1-4]Q)\s*-', heading)
                if not actual:
                    raise ValueError('fresh official PDF heading is unreadable')
                year, quarter, level = manifest['academicYear'], manifest['quarter'], source['level']
                if (int(actual[1]), actual[2]) != (year, quarter):
                    for directory in ('exam', 'exam-week-classes'):
                        name = f'{directory}/{level}/{year}-{quarter.lower()}.json'
                        if (root / name).exists() and load(root / name) != json.loads(git(root, 'show', f'HEAD:{name}')):
                            raise ValueError('automation changed a historical or pending quarter without a matching PDF')
                    continue  # Keep historical/pending scopes when a URL is reused.
                feed = load(root / f'exam/{level}/{year}-{quarter.lower()}.json')
                published_source = next(s for s in feed['source'] if s['id'] == source['id'])
                if published_source.get('sha256') != hashlib.sha256(content).hexdigest():
                    raise ValueError('published exam provenance differs from the fresh official PDF')
                classes = extract_classes(Path(temporary.name), calendar=load(root / f'academic-calendar/{year}.json'),
                                          quarter=quarter, level=level, manifest=manifest, exam_feed=feed)
                published = load(root / f'exam-week-classes/{level}/{year}-{quarter.lower()}.json')
                if classes['entries'] != published['entries']:
                    raise ValueError('published exam-week classes differ from fresh official PDF rows')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=DATASETS, default="exams")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--base", required=True)
    parser.add_argument("--prepare", type=Path)
    parser.add_argument("--bundle", type=Path)
    args = parser.parse_args()
    try:
        root = args.root.resolve()
        if args.prepare:
            bundle = prepare(root, args.base, args.dataset)
            args.prepare.parent.mkdir(parents=True, exist_ok=True)
            args.prepare.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
            print(json.dumps({"preparedFiles": sorted(bundle["files"])}))
        else:
            if os.environ.get("GITHUB_REF") != "refs/heads/main" or os.environ.get("GITHUB_REPOSITORY") != REPOSITORY:
                raise ValueError("direct publication runs only from this repository's main branch")
            if not args.bundle:
                parser.error("--bundle is required for publication")
            from source_monitor import snapshot
            bundle = load(args.bundle)
            if bundle.get('schemaVersion') != 2 or bundle.get('review') is None:
                raise ValueError('publication requires a prepared public-source review bundle')
            fresh, documents = snapshot(root, args.dataset)
            files = apply_and_validate(root, bundle, args.base, fresh_state=fresh, dataset=args.dataset)
            if args.dataset == 'exams':
                verify_public_exam_artifacts(root, documents)
            subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=root, check=True)
            result = publish(args.base, files, os.environ.get("DATA_PR_TOKEN"), os.environ.get("STATUS_TOKEN"),
                             f"https://github.com/{REPOSITORY}/actions/runs/{os.environ['GITHUB_RUN_ID']}", dataset=args.dataset)
            print(json.dumps(result))
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print(f"data publication failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
