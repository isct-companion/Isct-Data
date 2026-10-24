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
        self.assertEqual(len(gaps), 2)
        self.assertEqual(snapshot(ROOT, download)[0], first)
        revised = snapshot(ROOT, lambda url: b'%PDF-revised' if url.endswith('.pdf') else download(url))[0]
        self.assertNotEqual(first, revised)

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


class PublicationBoundary(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'data'
        shutil.copytree(ROOT, self.root, ignore=shutil.ignore_patterns('.git', '.exam-runs', '__pycache__'))
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        self.runs = self.root / '.exam-runs'
        self.runs.mkdir()

    def write(self, name, value):
        (self.runs / name).write_text(json.dumps(value))
        return f'.exam-runs/{name}'

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
        state, _, _ = snapshot(self.root, lambda url: b'%PDF-test' if url.endswith('.pdf') else b'<html></html>')
        coverage = {'sources': [], 'lmsDiscovery': 'unavailable_no_lms_session'}
        for path in sorted((self.root / 'source-manifest').glob('*.json')):
            for source in json.loads(path.read_text())['sources']:
                coverage['sources'].append({'manifest': str(path.relative_to(self.root)), 'sourceId': source['id'],
                                            'reviewedScope': path.stem, 'unresolvedFacts': [],
                                            'outcome': 'reviewed' if source['access'] == 'public' else 'unavailable_no_lms_session'})
        state_path = self.write('state.json', state)
        incomplete = copy.deepcopy(coverage)
        incomplete['sources'].pop()
        with self.assertRaises(ValueError):
            acknowledge_sources(self.root, state_path, self.write('coverage.json', incomplete))
        self.assertFalse((self.root / STATE).exists())
        coverage_path = self.write('coverage.json', coverage)
        acknowledge_sources(self.root, state_path, coverage_path)
        self.assertEqual(json.loads((self.root / STATE).read_text()), state)
        manifest = self.root / 'source-manifest/2026-3q.json'
        manifest.write_text(manifest.read_text() + ' ')
        with self.assertRaises(ValueError):
            acknowledge_sources(self.root, state_path, coverage_path)
        self.assertEqual(json.loads((self.root / STATE).read_text()), state)


if __name__ == '__main__':
    unittest.main()
