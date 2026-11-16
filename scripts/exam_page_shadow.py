#!/usr/bin/env python3
"""Prepare and grade a read-only exam review replay from official PDF captures."""
import argparse
from collections import defaultdict
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from zipfile import BadZipFile, ZipFile

import pdfplumber
from pdfplumber.utils.exceptions import PdfminerException
from pypdfium2 import PdfiumError

from check_exam_sources import allowed_url, fetch
from exam_page_scope import digest, locate_pages
from extract_exam_timetable import read_rows

ROOT = Path(__file__).resolve().parent.parent
REPOSITORY = 'isct-companion/Isct-Data'
LEVELS = {'undergraduate': '学士課程', 'graduate': '大学院課程'}
FIELDS = ('date', 'periodText', 'room', 'withdrawn', 'titleJa', 'titleEn', 'roomNote', 'note')
SLOTS = ('full-a', 'full-b', 'pages-a', 'pages-b')
HEADING = re.compile(r'Schedule of Final Exams(?: and Classes)?\s*-\s*(\d{4})\s+([1-4]Q)\s*-')


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def public_sources(root):
    sources = {}
    for path in sorted((root / 'source-manifest').glob('*.json')):
        for source in load(path)['sources']:
            if source['access'] == 'public' and source['scope'] == 'central_final_exam_timetable':
                sources[source['level']] = allowed_url(source['artifactUrl'])
    if sources.keys() != LEVELS.keys():
        raise ValueError('shadow review requires the public undergraduate and graduate timetable URLs')
    return sources


def api(endpoint):
    result = subprocess.run(['gh', 'api', f'repos/{REPOSITORY}/{endpoint}'],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
    if result.returncode:
        raise ValueError(f'GitHub could not read {endpoint}: {result.stderr.decode(errors="replace").strip()}')
    return result.stdout


def evidence_archive(run_id):
    if not re.fullmatch(r'[1-9][0-9]{0,19}', run_id):
        raise ValueError('source workflow run ID must be a positive integer')
    run = json.loads(api(f'actions/runs/{run_id}'))
    if (run['head_repository']['full_name'] != REPOSITORY or run['head_branch'] != 'main'
            or run['path'] != '.github/workflows/update-exams.yml' or run['status'] != 'completed'
            or run['event'] not in ('schedule', 'workflow_dispatch')):
        raise ValueError(f'run {run_id} is not a completed production exam update')
    artifacts = json.loads(api(f'actions/runs/{run_id}/artifacts?per_page=100'))['artifacts']
    for slot in ('a', 'b'):
        for artifact in artifacts:
            if artifact['name'] != f'public-source-review-{slot}' or artifact['expired']:
                continue
            content = api(f'actions/artifacts/{int(artifact["id"])}/zip')
            if artifact.get('digest') and 'sha256:' + digest(content) != artifact['digest']:
                raise ValueError(f'archive checksum differs for run {run_id}')
            return content
    raise ValueError(f'run {run_id} has no retained source evidence')


def read_snapshot(content, sources):
    def member(archive, name, limit):
        info = archive.getinfo(name)
        if info.file_size > limit:
            raise ValueError(f'archive member exceeds size limit: {name}')
        return archive.read(info)

    with ZipFile(io.BytesIO(content)) as archive:
        acquisition = json.loads(member(archive, '.data-runs/acquisition.json', 1024 * 1024))
        state = json.loads(member(archive, '.data-runs/source-state.json', 1024 * 1024))
        if acquisition['dataset'] != 'exams':
            raise ValueError('source evidence does not belong to the exam workflow')
        snapshot = {}
        for level, url in sources.items():
            records = [item for item in acquisition['documents'] if item['url'] == url]
            if len(records) != 1:
                raise ValueError(f'expected exactly one official {level} PDF in the archive')
            record = records[0]
            pdf = member(archive, record['path'], 32 * 1024 * 1024)
            if not pdf.startswith(b'%PDF-') or digest(pdf) != record['sha256'] or digest(pdf) != state['sources'][url]:
                raise ValueError(f'official {level} PDF does not match the recorded source hash')
            snapshot[level] = pdf
    return snapshot


def timetable_terms(path, level):
    with pdfplumber.open(path) as pdf:
        text = pdf.pages[0].extract_text() if pdf.pages else ''
    heading = HEADING.search(text or '')
    if not heading or LEVELS[level] not in (text or ''):
        raise ValueError(f'cannot verify the official {level} timetable heading')
    return heading.groups()


def grouped(rows, level):
    records = defaultdict(list)
    for row in rows:
        for code in row['codes']:
            key = f'{level}:{row["kind"]}:{code}'
            records[key].append([row[field] for field in FIELDS])
    return {key: sorted(values, key=json.dumps) for key, values in records.items()}


def prepare(root, output, before, after, sources):
    packets = {'full': [], 'pages': []}
    truth, documents = {}, {}
    for level in LEVELS:
        old_hash, new_hash = digest(before[level]), digest(after[level])
        meta = {'url': sources[level], 'beforeSha256': old_hash, 'afterSha256': new_hash}
        documents[level] = meta
        if old_hash == new_hash:
            meta.update(scope='none', reason='raw PDF bytes match', changedPages=[])
            continue
        work = output / 'pdfs'
        work.mkdir(parents=True, exist_ok=True)
        old, new = (work / f'{level}-{side}.pdf' for side in ('before', 'after'))
        old.write_bytes(before[level])
        new.write_bytes(after[level])
        year, term = timetable_terms(old, level)
        if (year, term) != timetable_terms(new, level):
            raise ValueError('shadow replay needs two editions of the same academic quarter')
        ranges = load(root / 'academic-calendar' / f'{year}.json')['examRanges'][term]
        date_range = ranges[0]['start'], ranges[-1]['end']
        old_rows, new_rows = (read_rows(path, date_range) for path in (old, new))
        if any(not rows or any(not row['codes'] or row['periods'] is None for row in rows)
               for rows in (old_rows, new_rows)):
            raise ValueError(f'{level}: full reference extraction is incomplete')
        try:
            scope, reason, pages = locate_pages(old, new, date_range)
        except (ValueError, PdfminerException, PdfiumError):
            scope, reason, pages = 'document', 'page alignment or rendering failed', []
        groups_before, groups_after = (grouped(rows, level) for rows in (old_rows, new_rows))
        codes = {code for row in (*old_rows, *new_rows) if row['page'] in pages for code in row['codes']}
        full = [[key, groups_before.get(key, []), groups_after.get(key, [])]
                for key in sorted(groups_before.keys() | groups_after.keys())]
        scoped = full if scope == 'document' else [item for item in full if item[0].split(':')[-1] in codes]
        expected = {key: [a, b] for key, a, b in full if a != b}
        missed = sorted(expected.keys() - {key for key, _, _ in scoped})
        meta.update(scope=scope, reason=reason, changedPages=pages, fullGroups=len(full),
                    pageGroups=len(scoped), missedGroups=missed)
        truth.update(expected)
        packets['full'].extend(full)
        packets['pages'].extend(scoped)
    if not packets['full']:
        raise ValueError('the official PDFs have identical bytes; choose two different captures')
    for arm, rows in packets.items():
        path = output / arm / 'evidence.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join(json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n'
                                for row in rows), encoding='utf-8')
    save(output / 'report' / 'reference.json', {'fields': FIELDS, 'documents': documents, 'expected': truth})


def compare_answer(path, reference):
    expected = reference['expected']
    result = load(path)
    items = result['changes']
    if (not isinstance(items, list) or set(result) != {'changes'}
            or any(not isinstance(item, dict) or set(item) != {'id', 'before', 'after'}
                   or not isinstance(item['id'], str)
                   or any(not isinstance(item[side], list) for side in ('before', 'after'))
                   for item in items)):
        raise ValueError('answer does not match the review format')
    ids = [item['id'] for item in items]
    answers = {item['id']: [sorted(item[side], key=json.dumps) for side in ('before', 'after')] for item in items}
    wrong = sorted(key for key in expected.keys() & answers.keys()
                   if json.dumps(expected[key]) != json.dumps(answers[key]))
    return {
        'missing': sorted(expected.keys() - answers.keys()),
        'extra': sorted(answers.keys() - expected.keys()),
        'wrong': wrong,
        'duplicateIds': len(ids) != len(set(ids)),
    }


def grade(report_path, answers_path, out):
    reference = load(report_path)
    results = {}
    for slot in SLOTS:
        try:
            results[slot] = compare_answer(answers_path / f'exam-shadow-answer-{slot}' / 'answer.json', reference)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            results[slot] = {'error': str(error)}
    passed = (not any(doc.get('missedGroups') for doc in reference['documents'].values())
              and all(not any(result.values()) for result in results.values()))
    data = {'pass': passed, 'documents': reference['documents'],
            'changedGroups': len(reference['expected']), 'reviewers': results}
    save(out, data)
    lines = ['## Exam page shadow', '',
             '| Timetable | Scope | Changed pages | Full groups | Shadow groups | Scope misses |',
             '| --- | --- | --- | ---: | ---: | ---: |']
    for level, spec in data['documents'].items():
        pages = ', '.join(map(str, spec['changedPages']))
        lines.append(f"| {level} | {spec['scope']} | {pages} | {spec.get('fullGroups', 0)} | "
                     f"{spec.get('pageGroups', 0)} | {len(spec.get('missedGroups', []))} |")
    lines += ['', f"Reference changes: {data['changedGroups']}. "
              f"All four independent reviews match: {'yes' if passed else 'no'}.", '']
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a', encoding='utf-8') as summary:
            summary.write('\n'.join(lines))
    print(json.dumps(data, ensure_ascii=False))
    return passed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prep = commands.add_parser('prepare')
    prep.add_argument('--before-run', required=True)
    prep.add_argument('--after-run', default='')
    prep.add_argument('--output', type=Path, required=True)
    check = commands.add_parser('grade')
    check.add_argument('--reference', type=Path, required=True)
    check.add_argument('--answers', type=Path, required=True)
    check.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'grade':
            return 0 if grade(args.reference, args.answers, args.output) else 1
        sources = public_sources(ROOT)
        before = read_snapshot(evidence_archive(args.before_run), sources)
        after = (read_snapshot(evidence_archive(args.after_run), sources) if args.after_run
                 else {level: fetch(url) for level, url in sources.items()})
        prepare(ROOT, args.output, before, after, sources)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, BadZipFile, PdfminerException) as error:
        print(f'exam shadow failed: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
