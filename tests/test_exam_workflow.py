"""Publication boundaries: stale/partial reviews must never advance public data."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from check_exam_sources import OfficialRedirects, PdfLinks, STATE, allowed_url, snapshot
from exam_workflow import acknowledge_sources, check_all, run
from merge_exam_candidates import canonical_hash
from publish_exam_update import apply_and_validate, prepare, publish
from data_workflow import apply_review
from dataset_rules import state_path
from source_monitor import snapshot as public_snapshot
from update_subscription_index import normalize


class SourcePolling(unittest.TestCase):
    def test_deduplicates_shared_quarter_urls_and_detects_replaced_pdf(self):
        calls = []
        # Only the network transport is substituted: deterministic fixtures let
        # this test check discovery and content hashes without a school outage.
        def download(url):
            calls.append(url)
            return b'%PDF-original' if url.endswith('.pdf') else b'<a href="/revised.pdf">new</a>'
        first, _, gaps = snapshot(ROOT, download)
        self.assertEqual(len(calls), len(set(calls)))
        self.assertIn('https://www.titech.ac.jp/revised.pdf', first['sources'])
        self.assertEqual(gaps, [])
        self.assertEqual(snapshot(ROOT, download)[0], first)
        revised = snapshot(ROOT, lambda url: b'%PDF-revised' if url.endswith('.pdf') else download(url))[0]
        self.assertNotEqual(first, revised)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            shutil.copytree(ROOT / 'source-manifest', target / 'source-manifest')
            path = target / 'source-manifest/2026-2q.json'
            value = json.loads(path.read_text())
            next(s for s in value['sources'] if s['access'] != 'public')['url'] += '&manual-update=1'
            path.write_text(json.dumps(value))
            self.assertEqual(first, snapshot(target, download)[0])

    def test_rejects_off_host_links_and_redirects_before_fetch(self):
        for url in ('http://www.titech.ac.jp/a.pdf', 'https://titech.ac.jp/a.pdf',
                    'https://www.titech.ac.jp.evil.example/a.pdf',
                    'https://user@www.titech.ac.jp/a.pdf', 'https://www.titech.ac.jp:8443/a.pdf'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                allowed_url(url)
        with self.assertRaises(ValueError):
            OfficialRedirects().redirect_request(None, None, 302, '', {}, 'https://other.example/a.pdf')
        with self.assertRaises(ValueError):
            PdfLinks('https://www.titech.ac.jp/').feed('<a href="https://other.example/a.pdf">new</a>')
        with self.assertRaises(OSError):
            snapshot(ROOT, lambda url: (_ for _ in ()).throw(OSError('unavailable')))

    def test_public_profiles_limit_cabinet_office_to_calendar_and_ignore_manual_sources(self):
        for dataset in ('academic-calendar', 'departments', 'important-dates', 'exams'):
            calls = []
            def download(url):
                calls.append(url)
                return b'public source bytes'
            public_snapshot(ROOT, dataset, download)
            self.assertTrue(calls)
            self.assertFalse(any('lms.' in url for url in calls))
            self.assertEqual(any('www8.cao.go.jp' in url for url in calls), dataset == 'academic-calendar')


    def test_source_graph_decodes_legacy_guide_html_and_tracks_holiday_csv(self):
        def download(url):
            if url.endswith('.pdf'):
                return b'%PDF-fixture'
            if url.endswith('.csv'):
                return '日付,祝日'.encode('cp932')
            link = 'syukujitsu.csv' if 'www8.cao.go.jp' in url else '/extra.pdf'
            return f'<html><meta charset="Shift_JIS"><a href="{link}">公開資料</a></html>'.encode('cp932')
        guides, _ = public_snapshot(ROOT, 'departments', download)
        self.assertIn('https://www.titech.ac.jp/extra.pdf', guides['sources'])
        calendar, _ = public_snapshot(ROOT, 'academic-calendar', download)
        self.assertIn('https://www8.cao.go.jp/chosei/shukujitsu/syukujitsu.csv', calendar['sources'])



class PublicationBoundary(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'data'
        shutil.copytree(ROOT, self.root, ignore=shutil.ignore_patterns('.git', '.exam-runs', '.data-runs', '__pycache__'))
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        self.runs = self.root / '.exam-runs'
        self.runs.mkdir()

    def write(self, name, value):
        (self.runs / name).write_text(json.dumps(value))
        return f'.exam-runs/{name}'

    def commit_base(self):
        subprocess.run(['git', 'add', '.'], cwd=self.root, check=True)
        subprocess.run(['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                        '-c', 'commit.gpgsign=false', 'commit', '-qm', 'fixture'], cwd=self.root, check=True)
        return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=self.root, text=True).strip()

    def public_bytes(self):
        return {str(p.relative_to(self.root)): p.read_bytes()
                for folder in ('exam', 'exam-week-classes') for p in (self.root / folder).rglob('*.json')} | {
                    p: (self.root / p).read_bytes() for p in ('index.json', 'index.sha256')}

    def review(self):
        feed = json.loads((self.root / 'exam/undergraduate/2026-3q.json').read_text())
        source = json.loads((self.root / 'source-manifest/2026-3q.json').read_text())['sources'][0]
        source = dict(source, url=source['artifactUrl'], title='Reviewed official timetable',
                      landingPageUrl=source['url'], retrievedAt='2026-10-24T00:00:00Z')
        evidence = 'TST.A101 final 2026-11-27 periods 1-2 room M-101'
        return {'schemaVersion': 1, 'academicYear': 2026, 'quarter': '3Q', 'level': 'undergraduate',
                'baseFeedHash': canonical_hash(feed), 'sources': [source], 'candidates': [{
                    'id': 'test', 'confirmed': True, 'assessmentKind': 'final', 'assessmentId': 'final',
                    'newAssessment': True, 'courseCode': 'TST.A101', 'quarter': '3Q',
                    'sourceId': source['id'], 'date': '2026-11-27', 'periods': [1, 2],
                    'room': {'ja': 'M-101'}, 'label': {'ja': 'テスト'},
                    'evidenceText': evidence, 'evidenceHash': hashlib.sha256(evidence.encode()).hexdigest(),
                    'evidenceContext': {'identity': 'TST.A101', 'time': '2026-11-27 1-2'},
                    'publishFields': ['courseCode', 'quarter', 'date', 'periods', 'room', 'label', 'sourceIds'],
                }]}

    def test_scoped_update_is_idempotent_and_keeps_unrelated_references(self):
        before = self.public_bytes()
        review = self.review()
        path = self.write('candidates.json', review)
        result = run(self.root, 2026, '3Q', 'undergraduate', path)
        self.assertTrue(result['changed'])
        check_all(self.root)
        after = self.public_bytes()
        self.assertEqual({p for p in before if before[p] != after[p]},
                         {'exam/undergraduate/2026-3q.json', 'index.json', 'index.sha256'})
        feed = json.loads((self.root / 'exam/undergraduate/2026-3q.json').read_text())
        review['baseFeedHash'] = canonical_hash(feed)
        self.write('candidates.json', review)
        run(self.root, 2026, '3Q', 'undergraduate', path)
        self.assertEqual(self.public_bytes(), after)

    def test_stale_candidate_and_wrong_scope_leave_all_public_bytes_unchanged(self):
        before = self.public_bytes()
        for field, value in (('baseFeedHash', '0' * 64), ('quarter', '2Q')):
            review = self.review()
            review[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                run(self.root, 2026, '3Q', 'undergraduate', self.write('bad.json', review))
            self.assertEqual(self.public_bytes(), before)

    def test_source_baseline_requires_complete_coverage_and_current_manifests(self):
        (self.root / STATE).unlink(missing_ok=True)
        state, _, _ = snapshot(self.root, lambda url: b'%PDF-test' if url.endswith('.pdf') else b'<html></html>')
        coverage = {'sources': []}
        for path in sorted((self.root / 'source-manifest').glob('*.json')):
            for source in json.loads(path.read_text())['sources']:
                if source['access'] != 'public':
                    continue
                coverage['sources'].append({'manifest': str(path.relative_to(self.root)), 'sourceId': source['id'],
                                            'reviewedScope': path.stem, 'unresolvedFacts': [],
                                            'outcome': 'reviewed'})
        state_path = self.write('state.json', state)
        base = self.commit_base()
        incomplete = copy.deepcopy(coverage)
        incomplete['sources'].pop()
        with self.assertRaises(ValueError):
            acknowledge_sources(self.root, state_path, self.write('coverage.json', incomplete))
        self.assertFalse((self.root / STATE).exists())
        coverage_path = self.write('coverage.json', coverage)
        acknowledge_sources(self.root, state_path, coverage_path)
        self.assertEqual(json.loads((self.root / STATE).read_text()), state)
        bundle = {'schemaVersion': 1, 'baseSha': base, 'files': {STATE: json.dumps(state)},
                  'observedState': state, 'coverage': coverage}
        files = apply_and_validate(self.root, bundle, base, fresh_state=state)
        self.assertEqual(set(files), {STATE})
        with self.assertRaises(ValueError):
            apply_and_validate(self.root, bundle, base, fresh_state={})
        manifest = self.root / 'source-manifest/2026-3q.json'
        value = json.loads(manifest.read_text())
        value['sources'][0]['artifactUrl'] += '?revision=1'
        manifest.write_text(json.dumps(value))
        with self.assertRaises(ValueError):
            acknowledge_sources(self.root, state_path, coverage_path)
        self.assertEqual(json.loads((self.root / STATE).read_text()), state)

    def test_direct_publication_rejects_script_changes_traversal_and_stale_inputs(self):
        base = self.commit_base()
        before = self.public_bytes()
        for name in ('scripts/exam_workflow.py', '../escape.json', 'exam/undergraduate/../../scripts/evil.py'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                apply_and_validate(self.root, {'schemaVersion': 1, 'baseSha': base, 'files': {name: '{}'}}, base)
            self.assertEqual(before, self.public_bytes())
        with self.assertRaises(ValueError):
            apply_and_validate(self.root, {'schemaVersion': 1, 'baseSha': '0' * 40, 'files': {}}, base)
        (self.root / 'scripts/exam_workflow.py').write_text('untrusted script')
        with self.assertRaises(ValueError):
            prepare(self.root, base)

    def test_public_dataset_writer_and_publisher_keep_unrelated_subscriptions(self):
        for dataset in ('academic-calendar', 'departments', 'important-dates'):
            with self.subTest(dataset=dataset):
                base = self.commit_base()
                path = f'{dataset}/2026.json'
                original_index = json.loads((self.root / 'index.json').read_text())
                original = json.loads((self.root / path).read_text())
                updated = copy.deepcopy(original); updated['source'][0]['title'] += ' reviewed'
                state, documents = public_snapshot(self.root, dataset, lambda url: b'public source bytes')
                directory = self.root / '.data-runs'; directory.mkdir(exist_ok=True)
                records = []
                for n, (url, content) in enumerate(documents.items()):
                    local = directory / f'{n}.html'; local.write_bytes(content)
                    records.append({'url': url, 'path': str(local.relative_to(self.root))})
                (directory / 'source-state.json').write_text(json.dumps(state))
                (directory / 'acquisition.json').write_text(json.dumps({'documents': records}))
                review = {'dataset': dataset, 'status': 'approved', 'summary': 'Reviewed public source',
                          'sources': [{'url': u, 'outcome': 'reviewed', 'reviewedScope': '2026', 'unresolvedFacts': []} for u in state['sources']],
                          'updates': {path: updated}, 'baseHashes': {path: canonical_hash(normalize(original))}}
                (directory / 'review.json').write_text(json.dumps(review))
                apply_review(self.root, dataset)
                bundle = prepare(self.root, base, dataset)
                self.assertEqual(bundle['schemaVersion'], 2)
                self.assertIn(path, bundle['files'])
                subprocess.run(['git', 'restore', '.'], cwd=self.root, check=True)
                result = apply_and_validate(self.root, bundle, base, fresh_state=state, dataset=dataset)
                self.assertIn(path, result)
                current_index = json.loads((self.root / 'index.json').read_text())
                # A public calendar/event/guide update cannot change exam or manual schedule subscriptions.
                for year in original_index['academicYears']:
                    for field in ('exams', 'examWeekClasses', 'classSchedules'):
                        self.assertEqual(current_index['academicYears'][year].get(field), original_index['academicYears'][year].get(field))
                forbidden = copy.deepcopy(bundle)
                forbidden['files'] = {'class-schedules/2026.json': '{}'}
                subprocess.run(['git', 'restore', '.'], cwd=self.root, check=True)
                with self.assertRaises(ValueError):
                    apply_and_validate(self.root, forbidden, base, fresh_state=state, dataset=dataset)
                subprocess.run(['git', 'restore', '.'], cwd=self.root, check=True)

    def test_automatic_publisher_cannot_change_manual_exam_facts(self):
        base = self.commit_base()
        path = 'exam/undergraduate/2026-2q.json'
        feed = json.loads((self.root / path).read_text())
        manual_id = '2026-2Q-undergraduate-CSC.T251-final'
        next(e for e in feed['entries'] if e['id'] == manual_id)['date'] = '2026-07-30'
        before = self.public_bytes()
        bundle = {'schemaVersion': 1, 'baseSha': base, 'files': {path: json.dumps(feed)}}
        with self.assertRaisesRegex(ValueError, 'manually maintained'):
            apply_and_validate(self.root, bundle, base)
        self.assertEqual(self.public_bytes(), before)
        public_feed = json.loads((self.root / path).read_text())
        public_feed['source'][0]['url'] = 'https://outside.example/unreviewed.pdf'
        bundle['files'][path] = json.dumps(public_feed)
        bundle['observedState'] = snapshot(self.root, lambda url: b'public bytes')[0]
        with self.assertRaisesRegex(ValueError, 'not polled'):
            apply_and_validate(self.root, bundle, base)
        self.assertEqual(self.public_bytes(), before)

    def test_direct_publication_records_real_check_before_nonforced_ref_change(self):
        calls = []
        # Substitute only the GitHub transport. Publication ordering, credential
        # separation, commit ancestry and the non-force ref update run unchanged.
        def api(token, method, path, body=None):
            calls.append((token, method, path, body))
            if path == 'git/ref/heads/main':
                return {'object': {'sha': 'base'}}
            if path == 'git/commits/base':
                return {'tree': {'sha': 'base-tree'}}
            return {'sha': 'new'}
        result = publish('base', {'index.sha256': 'data'}, 'writer', 'actions', 'https://example.invalid/run', api=api)
        self.assertTrue(result['changed'])
        self.assertEqual(calls[-2][0:3], ('actions', 'POST', 'statuses/new'))
        self.assertEqual(calls[-1], ('writer', 'PATCH', 'git/refs/heads/main', {'sha': 'new', 'force': False}))
        self.assertEqual(next(c[3]['parents'] for c in calls if c[2] == 'git/commits'), ['base'])
        calls.clear()
        def stale(token, method, path, body=None):
            calls.append(path)
            return {'object': {'sha': 'advanced'}}
        with self.assertRaises(ValueError):
            publish('base', {'index.sha256': 'data'}, 'writer', 'actions', 'https://example.invalid/run', api=stale)
        self.assertEqual(calls, ['git/ref/heads/main'])


if __name__ == '__main__':
    unittest.main()
