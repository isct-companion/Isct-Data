#!/usr/bin/env python3
"""Read-only queries over the prepared evidence in .data-runs/, so agents read
the few lines or table cells they need instead of whole text dumps or images.

  python3 scripts/evidence.py list
  python3 scripts/evidence.py grep REGEX [--source NAME] [--context 1]
  python3 scripts/evidence.py page NAME N            # text of one PDF page, layout kept
  python3 scripts/evidence.py tables NAME N          # tables on one PDF page, tab-separated
  python3 scripts/evidence.py struck NAME N          # text under strike-through lines on a page
  python3 scripts/evidence.py rows SCOPE [--code C] [--date D] [--revised]   # exams only
  python3 scripts/evidence.py record FILE KEY        # one record of a data or candidate JSON

NAME is a file stem from `list` (a unique prefix is enough). Nothing is written.
"""
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
RUN = ROOT / '.data-runs'
LIMIT = 200


def documents():
    acquisition = json.loads((RUN / 'acquisition.json').read_text())
    return [dict(d, stem=Path(d['path']).stem) for d in acquisition['documents']]


def find(name):
    matches = [d for d in documents() if d['stem'] == name] or [d for d in documents() if d['stem'].startswith(name)]
    if len(matches) != 1:
        raise ValueError(f'{name!r} matches {len(matches)} sources; use a stem from `list`')
    return matches[0]


def pdf_page(name, number):
    import pdfplumber
    document = find(name)
    if not document['path'].endswith('.pdf'):
        raise ValueError(f'{name} is not a PDF')
    pdf = pdfplumber.open(ROOT / document['path'])
    if not 1 <= number <= len(pdf.pages):
        raise ValueError(f'{name} has {len(pdf.pages)} pages')
    return pdf, pdf.pages[number - 1]


def emit(lines):
    lines = list(lines)
    for line in lines[:LIMIT]:
        print(line)
    if len(lines) > LIMIT:
        print(f'... {len(lines) - LIMIT} more lines; narrow the query')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('list')
    grep = sub.add_parser('grep'); grep.add_argument('pattern'); grep.add_argument('--source')
    grep.add_argument('--context', type=int, default=0)
    for command in ('page', 'tables', 'struck'):
        p = sub.add_parser(command); p.add_argument('name'); p.add_argument('number', type=int)
    rows = sub.add_parser('rows'); rows.add_argument('scope', help='e.g. 2026-3q-undergraduate')
    rows.add_argument('--code'); rows.add_argument('--date'); rows.add_argument('--revised', action='store_true')
    record = sub.add_parser('record'); record.add_argument('file'); record.add_argument('key')
    args = parser.parse_args()
    try:
        if args.command == 'list':
            for d in documents():
                pages = ''
                if d['path'].endswith('.pdf'):
                    import pdfplumber
                    with pdfplumber.open(ROOT / d['path']) as pdf:
                        pages = f'  {len(pdf.pages)} pages'
                print(f'{d["stem"]}  {d["url"]}{pages}')
        elif args.command == 'grep':
            pattern = re.compile(args.pattern)
            out = []
            for d in documents():
                if args.source and not d['stem'].startswith(args.source):
                    continue
                text = (ROOT / d['path']).with_suffix('.txt')
                if not text.exists():
                    continue
                lines, page = text.read_text().splitlines(), ''
                for i, line in enumerate(lines):
                    marker = re.fullmatch(r'--- page (\d+) ---', line)
                    if marker:
                        page = f' p{marker[1]}'
                    elif pattern.search(line):
                        window = lines[max(0, i - args.context):i + args.context + 1]
                        out.append(f'{d["stem"]}{page} L{i + 1}: ' + ' | '.join(window))
            emit(out or ['no match'])
        elif args.command == 'page':
            pdf, page = pdf_page(args.name, args.number)
            emit((page.extract_text(layout=True) or '').splitlines())
        elif args.command == 'tables':
            pdf, page = pdf_page(args.name, args.number)
            out = []
            for n, table in enumerate(page.extract_tables(), 1):
                out.append(f'## table {n}')
                out += ['\t'.join((cell or '').replace('\n', ' ') for cell in row) for row in table]
            emit(out or ['no tables found on this page'])
        elif args.command == 'struck':
            # Horizontal lines drawn through text are strike-throughs (withdrawn rows or superseded values).
            pdf, page = pdf_page(args.name, args.number)
            out = []
            for line in page.lines:
                if abs(line['top'] - line['bottom']) > 1:
                    continue
                words = [w['text'] for w in page.extract_words()
                         if w['top'] < line['top'] < w['bottom'] and w['x0'] < line['x1'] and w['x1'] > line['x0']]
                if words:
                    out.append(f'y={line["top"]:.0f}: ' + ' '.join(words))
            emit(out or ['no struck text on this page'])
        elif args.command == 'rows':
            data = json.loads((RUN / 'exams' / f'{args.scope}.rows.json').read_text())
            out = [json.dumps(r, ensure_ascii=False) for r in data
                   if (not args.code or any(c.startswith(args.code) for c in r.get('codes', [])))
                   and (not args.date or r.get('date') == args.date)
                   and (not args.revised or r.get('revised') or r.get('struck'))]
            emit(out or ['no matching rows'])
        else:
            path = (ROOT / args.file).resolve()
            path.relative_to(ROOT)
            sys.path.insert(0, str(ROOT / 'scripts'))
            from compare_publications import walk
            records = walk(json.loads(path.read_text()))
            hits = {k: v for k, (_, v) in records.items() if args.key in k}
            emit([f'{k}: {json.dumps(v, ensure_ascii=False)}' for k, v in hits.items()] or ['no matching record'])
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f'evidence query failed: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
