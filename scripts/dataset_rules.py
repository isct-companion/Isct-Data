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
# Datasets indexed by format version instead of by year: index group -> the source of one version. A later format is a
# new key and directory, and the old one stays, frozen. They are published by pull request from their private source
# repository, never by the automated workflows, so they are not in DATASETS and no publication path reaches them.
VERSIONED_INDEX = {'campusMap': 'campus-map/v{version}/campus-map.json.gz'}


def register_feeds(index, dataset, names):
    """Lists new yearly feed files in the index (non-exam datasets: one file per year); existing
    entries are kept, and their hashes are refreshed by update_subscription_index."""
    group, fields = DATASETS[dataset]['index']
    for name in names:
        index[group].setdefault(Path(name).stem, {}).setdefault(fields[0], name)
    return index


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


SCHEDULES = 'https://www.titech.ac.jp/student/students/life/schedules'


def monthly_pdf(year):
    return f'https://www.titech.ac.jp/student/pdf/life-schedules-month-ay{year}.pdf'


def source_urls(root, dataset):
    urls = {url for directory in DATASETS[dataset]['directories']
            for path in sorted((root / directory).rglob('*.json'))
            for url in urls_in(json.loads(path.read_text()))}
    if dataset in ('academic-calendar', 'important-dates'):
        # The live 授業日程 page shows only the newest year; earlier years move to their own archive
        # page, which no data file names once the live page moves on.
        years = sorted(int(path.stem) for path in (root / dataset).glob('*.json'))
        urls.update(f'{SCHEDULES}/{year}' for year in years[:-1])
    return urls


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
