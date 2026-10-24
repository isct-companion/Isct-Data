"""Dataset boundaries shared by acquisition, writers and trusted publication."""
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

DATASETS = {
    'academic-calendar': {'directories': ('academic-calendar',), 'index': ('academicYears', ('academicCalendar',)),
                          'hosts': ('www.titech.ac.jp', 'www8.cao.go.jp')},
    'departments': {'directories': ('departments',), 'index': ('admissionYears', ('departments',)),
                    'hosts': ('www.titech.ac.jp',)},
    'important-dates': {'directories': ('important-dates',), 'index': ('academicYears', ('importantDates',)),
                        'hosts': ('www.titech.ac.jp',)},
    'exams': {'directories': ('exam', 'exam-week-classes'), 'index': ('academicYears', ('exams', 'examWeekClasses')),
              'hosts': ('www.titech.ac.jp',)},
}


def state_path(dataset):
    return 'review/exam-source-state.json' if dataset == 'exams' else f'review/source-state/{dataset}.json'


def feed_path(name, dataset):
    if dataset == 'exams':
        return bool(re.fullmatch(r'(?:exam|exam-week-classes)/(?:undergraduate|graduate)/\d{4}-[1-4]q\.json', name))
    return bool(re.fullmatch(re.escape(dataset) + r'/\d{4}\.json', name))


def allowed_path(root, name, dataset):
    if name not in {'index.json', 'index.sha256', state_path(dataset)} and not feed_path(name, dataset):
        raise ValueError(f'publication path is outside {dataset}: {name}')
    path = root / name
    for part in (path, *path.parents):
        if part == root:
            break
        if part.is_symlink():
            raise ValueError('publication cannot follow symbolic links')
    path.resolve().relative_to(root.resolve())
    return path


def urls_in(item):
    urls = set()
    if isinstance(item, dict):
        for key, value in item.items():
            if key in {'url', 'landingPageUrl', 'artifactUrl', 'guidePdf'} and isinstance(value, str):
                urls.add(value)
            else:
                urls.update(urls_in(value))
    elif isinstance(item, list):
        for value in item:
            urls.update(urls_in(value))
    return urls


def source_urls(root, dataset):
    return {url for directory in DATASETS[dataset]['directories']
            for path in sorted((root / directory).rglob('*.json'))
            for url in urls_in(json.loads(path.read_text()))}


def assert_public_provenance(root, name, data, observed, dataset):
    if dataset != 'exams':
        sources = urls_in(data)
    else:
        manifest = json.loads((root / 'source-manifest' / f'{Path(name).stem}.json').read_text())
        known = {s['id']: s for s in manifest['sources'] if s['level'] == Path(name).parent.name}
        sources = set()
        for source in data['source']:
            if source['id'] not in known:
                raise ValueError('automated exam provenance uses an undeclared source')
            if known[source['id']]['access'] == 'public':
                sources.update(urls_in(source))
    if not sources.issubset(observed['sources']):
        raise ValueError('publication provenance names a source that was not polled')


def manual_exam_facts(root, feed):
    """Keep existing manually maintained source metadata and records immutable to automation."""
    manual = set()
    for path in (root / 'source-manifest').glob('*.json'):
        manual.update(s['id'] for s in json.loads(path.read_text())['sources'] if s['access'] != 'public')
    return {'source': {s['id']: s for s in feed['source'] if s['id'] in manual},
            'entries': {e['id']: e for e in feed['entries'] if manual.intersection(e['sourceIds'])}}
