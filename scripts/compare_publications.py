#!/usr/bin/env python3
"""Compare two independent agents' publication bundles; arbitrate only their differences.

Two author agents review the same official sources without seeing each other.
Their bundles are compared record by record:

* identical data -> the shared bundle goes to the trusted publisher unchanged;
* differences (or one author failed) -> a third agent sees only the differing
  records and picks, from the evidence, which version is right (A, B, or what
  main publishes today). This script then builds the final data from those
  picks, regenerates the index and prepares a normal publication bundle, which
  the trusted publisher validates exactly like any other.

No model decides what is "the same"; nothing a model writes is published
without the publisher's full checks.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys

from dataset_rules import DATASETS, state_path

ROOT = Path(__file__).resolve().parent.parent
DERIVED = {'index.json', 'index.sha256'}
EXAM_SAMPLE = 40
MAX_ITEMS = 150
SIDES = ('a', 'b', 'main')


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def walk(value, path=()):
    """Reviewable records of a data file: {display key: (path, value)}.

    Lists of objects with a unique string `id` (else `date`) are keyed by it, so
    a record keeps its identity when others are inserted before it."""
    if isinstance(value, dict):
        out = {}
        for key, child in value.items():
            out.update(walk(child, path + (('k', key),)))
        return out
    if isinstance(value, list) and value and all(isinstance(x, dict) for x in value):
        for field in ('id', 'date'):
            keys = [x.get(field) for x in value]
            if all(isinstance(k, str) for k in keys) and len(set(keys)) == len(keys):
                return {display(path + (('sel', field, x[field]),)): (path + (('sel', field, x[field]),), x) for x in value}
    return {display(path): (path, value)}


def display(path):
    out = ''
    for step in path:
        out += f'.{step[1]}' if step[0] == 'k' else f'[{step[1]}={step[2]}]'
    return out.lstrip('.')


def set_path(data, path, value):
    """Set (or with value None, delete) one record found by walk()."""
    *parents, last = [tuple(step) for step in path]
    node = data
    for i, step in enumerate(parents):
        following = parents[i + 1] if i + 1 < len(parents) else last
        empty = [] if following[0] == 'sel' else {}
        if step[0] == 'k':
            node = node.setdefault(step[1], empty)
        else:
            match = next((x for x in node if x.get(step[1]) == step[2]), None)
            if match is None:
                match = {step[1]: step[2]}; node.append(match)
            node = match
    if last[0] == 'k':
        if value is None:
            node.pop(last[1], None)
        else:
            node[last[1]] = value
    else:
        position = next((i for i, x in enumerate(node) if x.get(last[1]) == last[2]), None)
        if value is None:
            if position is not None:
                del node[position]
        elif position is None:
            node.append(value)
        else:
            node[position] = value


def head_json(root, name):
    try:
        return json.loads(subprocess.check_output(['git', 'show', f'HEAD:{name}'], cwd=root, text=True,
                                                  stderr=subprocess.DEVNULL))
    except subprocess.CalledProcessError:
        return None


def data_files(bundle, dataset):
    if bundle is None:
        return {}
    return {name: json.loads(text) for name, text in bundle['files'].items()
            if name not in DERIVED and name != state_path(dataset)}


def compare(root, dataset, paths, out):
    bundles = {}
    for side, path in paths.items():
        if path and Path(path).is_file():
            bundle = load(path)
            if bundle.get('dataset') != dataset or bundle.get('schemaVersion') != 2 or not bundle.get('review'):
                raise ValueError(f'author {side} bundle belongs to another dataset or has no review')
            bundles[side] = bundle
    if not bundles:
        raise ValueError('neither author produced an approved publication; nothing to compare')
    if len({b['baseSha'] for b in bundles.values()}) != 1:
        raise ValueError('the authors reviewed different main commits')
    if len({digest(b['observedState']) for b in bundles.values()}) != 1:
        raise ValueError('official sources changed between the two authors; rerun instead of arbitrating')
    files = {side: data_files(b, dataset) for side, b in bundles.items()}
    names = sorted(set().union(*files.values()))
    main = {name: head_json(root, name) for name in names}
    same = len(bundles) == 2 and files['a'] == files['b']
    items = []
    for name in names:
        records = {side: walk(files[side].get(name, main[name]) or {}) for side in bundles}
        records['main'] = walk(main[name] or {})
        for key in sorted(set().union(*(r.keys() for r in records.values()))):
            values = {side: records[side].get(key, (None, None))[1] for side in records}
            if len(bundles) == 2 and values['a'] == values['b']:
                continue  # Both authors agree; nothing to arbitrate.
            if len(bundles) == 1 and next(v for s, v in values.items() if s != 'main') == values['main']:
                continue  # The only author left this record as main has it.
            path = next(r[key][0] for r in records.values() if key in r)
            items.append({'id': f'{name}::{key}', 'file': name, 'key': key, 'path': [list(p) for p in path],
                          'options': {side: values[side] for side in records}})
    sampled = False
    if len(bundles) == 1 and dataset == 'exams' and len(items) > EXAM_SAMPLE:
        # The lone author's exam rows come from deterministic PDF geometry. The
        # arbiter checks every removal/cancellation/provenance item plus a
        # sample whose seed is fixed by the data, so no agent picks the sample.
        side = next(iter(bundles))
        def must(item):
            after = item['options'][side]
            return after is None or '[id=' not in item['key'] or (isinstance(after, dict) and after.get('status') == 'cancelled')
        required = [i for i in items if must(i)]
        rest = [i for i in items if not must(i)]
        seed = digest(files[side])
        items = sorted(required + random.Random(seed).sample(rest, min(len(rest), max(0, EXAM_SAMPLE - len(required)))),
                       key=lambda i: i['id'])
        sampled = True
    if not same and len(items) > MAX_ITEMS:
        raise ValueError(f'{len(items)} differing records exceed the {MAX_ITEMS}-record arbitration limit; '
                         'a person needs to review this update')
    out.mkdir(parents=True, exist_ok=True)
    comparison = {'dataset': dataset, 'same': same, 'authors': sorted(bundles), 'sampled': sampled, 'items': items}
    comparison['comparisonSha256'] = digest(comparison)
    save(out / 'comparison.json', comparison)
    for side, path in paths.items():
        if side in bundles:
            shutil.copyfile(path, out / f'publication-{side}.json')
    if same:
        shutil.copyfile(paths['a'], out / 'final.json')
    else:
        write_task(out, comparison, bundles)
    return {'dataset': dataset, 'same': same, 'authors': sorted(bundles), 'differences': len(items)}


def write_task(out, comparison, bundles):
    sides = {'a': 'author A', 'b': 'author B', 'main': 'what main publishes today'}
    verdict = {'dataset': comparison['dataset'], 'comparisonSha256': comparison['comparisonSha256'],
               'summary': '', 'choices': [{'id': i['id'], 'choice': 'pending', 'evidence': ''} for i in comparison['items']]}
    save(out / 'verdict.json', verdict)
    if len(bundles) == 2:
        intro = ['Two agents independently reviewed the same official sources and disagree on the records below.']
    else:
        missing = ({'a', 'b'} - set(bundles)).pop().upper()
        intro = [f'Author {missing} could not finish its review. Check the other author\'s changes below.']
    lines = [f'# Arbitrate {comparison["dataset"]}', '', *intro, '',
             'Each item in `.arbiter/comparison.json` has `options`: the record as ' +
             ', '.join(f'`{s}` ({sides[s]})' for s in SIDES) + '. `null` means the record is absent.',
             'Decide from the official evidence under `.data-runs/` which option is correct, not from which is more common.', '',
             'In `.arbiter/verdict.json` set each `choice` to one of the listed option names, and `evidence` to the',
             'source file and page/heading/line that proves it. If no option matches the source, set `choice` to',
             '`none` and explain in `evidence`; nothing will be published and a person will look at it.', '',
             'Then run `python3 scripts/compare_publications.py --dataset ' + comparison['dataset'] + ' --check-verdict`.',
             'Fix only what it lists (at most 3 checks). Then call `noop` with a short summary.',
             'Do not edit any other file.']
    (out / 'task.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def check_verdict(out, verdict_path):
    comparison, verdict = load(out / 'comparison.json'), load(verdict_path)
    if comparison['same']:
        raise ValueError('the authors agree; there is nothing to arbitrate')
    if verdict.get('comparisonSha256') != comparison['comparisonSha256'] or digest(
            {k: v for k, v in comparison.items() if k != 'comparisonSha256'}) != comparison['comparisonSha256']:
        raise ValueError('verdict is not bound to this comparison')
    choices = verdict.get('choices')
    if not isinstance(choices, list) or [c.get('id') for c in choices] != [i['id'] for i in comparison['items']]:
        raise ValueError('verdict must keep every prepared item, in order, with no additions')
    problems = []
    for item, choice in zip(comparison['items'], choices):
        if choice.get('choice') not in (*item['options'], 'none'):
            problems.append(f'{item["id"]}: choice must be one of {", ".join(item["options"])} or none')
        elif not str(choice.get('evidence', '')).strip():
            problems.append(f'{item["id"]}: evidence is required')
    if not str(verdict.get('summary', '')).strip():
        problems.append('summary is required')
    if problems:
        raise ValueError('; '.join(problems[:20]))
    unresolved = [c['id'] for c in choices if c['choice'] == 'none']
    return comparison, choices, unresolved


def resolve(root, dataset, out, verdict_path, base):
    """Build the final data from the arbiter's picks and prepare a publication bundle."""
    comparison, choices, unresolved = check_verdict(out, verdict_path)
    if unresolved:
        raise ValueError('the arbiter found no correct option for: ' + ', '.join(unresolved[:10]))
    bundles = {side: load(out / f'publication-{side}.json') for side in comparison['authors']}
    primary = bundles.get('a') or bundles['b']
    picks = {}
    for item, choice in zip(comparison['items'], choices):
        picks.setdefault(item['file'], []).append((item, choice['choice']))
    files = {side: data_files(b, dataset) for side, b in bundles.items()}
    names = sorted(set().union(*files.values()))
    for name in names:
        main_value = head_json(root, name)
        chosen = {c for _, c in picks.get(name, [])}
        if len(chosen) == 1 and (side := chosen.pop()) != 'main' and name in files[side]:
            value = files[side][name]  # One side wins the whole file: keep its exact layout.
        else:
            start = 'a' if 'a' in files else 'b'
            value = json.loads(json.dumps(files[start].get(name, main_value)))
            for item, side in picks.get(name, []):
                set_path(value, item['path'], item['options'][side])
        if value == main_value:
            continue
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    state_file = root / state_path(dataset)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(primary['observedState'], indent=2) + '\n', encoding='utf-8')
    subprocess.run([sys.executable, str(root / 'scripts/update_subscription_index.py'), '--data-root', str(root)],
                   check=True, stdout=subprocess.DEVNULL)
    run = root / '.data-runs'
    save(run / 'review.json', primary['review'])
    save(run / 'source-state.json', primary['observedState'])
    if dataset == 'exams':
        save(root / '.exam-runs/coverage.json', primary['coverage'])
    from publish_data import prepare
    bundle = prepare(root, base, dataset)
    (out / 'final.json').write_text(json.dumps(bundle, ensure_ascii=False), encoding='utf-8')
    return {'dataset': dataset, 'resolved': len(choices), 'files': sorted(bundle['files'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', choices=DATASETS, required=True)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--dir', type=Path, default=Path('.arbiter'))
    parser.add_argument('--a', type=Path)
    parser.add_argument('--b', type=Path)
    parser.add_argument('--verdict', type=Path)
    parser.add_argument('--base')
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument('--compare', action='store_true')
    operation.add_argument('--check-verdict', action='store_true')
    operation.add_argument('--resolve', action='store_true')
    args = parser.parse_args()
    root = args.root.resolve()
    out = args.dir if args.dir.is_absolute() else root / args.dir
    verdict = args.verdict or out / 'verdict.json'
    try:
        if args.compare:
            result = compare(root, args.dataset, {'a': args.a, 'b': args.b}, out)
            if os.environ.get('GITHUB_OUTPUT'):
                with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
                    output.write(f'same={str(result["same"]).lower()}\n')
            if os.environ.get('GITHUB_STEP_SUMMARY'):
                items = load(out / 'comparison.json')['items']
                with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as summary:
                    summary.write(f'### Author comparison: {args.dataset}\n\n')
                    summary.write('**Identical**: published without arbitration.\n' if result['same'] else
                                  f'**{len(items)} differing records** (finished authors: {", ".join(result["authors"])}): '
                                  'sent to the arbiter.\n\n' + ''.join(f'- `{i["id"]}`\n' for i in items[:30]))
        elif args.check_verdict:
            _, choices, unresolved = check_verdict(out, verdict)
            result = {'valid': True, 'items': len(choices), 'unresolved': unresolved}
        else:
            if not args.base:
                parser.error('--base is required to resolve')
            result = resolve(root, args.dataset, out, verdict, args.base)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        if args.check_verdict:
            print(f'Verdict check failed: {error}. Fix only .arbiter/verdict.json and check again (at most 3 checks).',
                  file=sys.stderr)
            return 1
        print(f'publication comparison failed: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
