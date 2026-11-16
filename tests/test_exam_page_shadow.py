import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import exam_page_shadow as shadow


class ShadowBoundaries(unittest.TestCase):
    def test_rejects_nonproduction_archive_run(self):
        run = {'head_repository': {'full_name': shadow.REPOSITORY}, 'head_branch': 'feature'}
        with patch.object(shadow, 'api', return_value=json.dumps(run)) as api:
            with self.assertRaisesRegex(ValueError, 'not a completed production'):
                shadow.evidence_archive('1234')
        api.assert_called_once_with('actions/runs/1234')

    def test_only_uses_official_pdfs_matching_both_acquisition_hashes(self):
        url = 'https://www.titech.ac.jp/student/pdf/life-undergraduate-exam-timetable.pdf'
        sources = {'undergraduate': url}
        content = b'%PDF-test'
        sha256 = shadow.digest(content)
        record = {'url': url, 'path': '.data-runs/sources/timetable.pdf', 'sha256': sha256}
        for expected, matches in ((sha256, True), (shadow.digest(b'changed'), False)):
            stream = io.BytesIO()
            with ZipFile(stream, 'w') as archive:
                archive.writestr('.data-runs/acquisition.json', json.dumps(
                    {'dataset': 'exams', 'documents': [record]}))
                archive.writestr('.data-runs/source-state.json', json.dumps({'sources': {url: expected}}))
                archive.writestr(record['path'], content)
            if matches:
                self.assertEqual(shadow.read_snapshot(stream.getvalue(), sources), {'undergraduate': content})
            else:
                with self.assertRaisesRegex(ValueError, 'does not match'):
                    shadow.read_snapshot(stream.getvalue(), sources)

    def test_changed_page_retains_other_occurrences_of_the_same_code(self):
        root = Path(__file__).resolve().parents[1]
        sources = shadow.public_sources(root)
        before = {'undergraduate': b'before', 'graduate': b'unchanged'}
        after = {'undergraduate': b'after', 'graduate': b'unchanged'}

        def row(code, page, date, room):
            return dict.fromkeys(shadow.FIELDS) | {
                'kind': 'class', 'codes': [code], 'page': page, 'date': date,
                'room': room, 'periods': [1, 2], 'periodText': '1-2', 'withdrawn': False,
            }

        old = [row('ABC.A101', 1, '2026-11-25', 'A'), row('ABC.A101', 3, '2026-12-02', 'B'),
               row('ABC.A102', 3, '2026-12-02', 'B')]
        new = [old[0] | {'room': 'C'}, *old[1:]]
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(shadow, 'timetable_terms', return_value=('2026', '3Q')),
            patch.object(shadow, 'read_rows', side_effect=[old, new]),
            patch.object(shadow, 'locate_pages', return_value=('pages', 'covered', [1])),
        ):
            output = Path(directory)
            shadow.prepare(root, output, before, after, sources)
            evidence = (output / 'pages/evidence.jsonl').read_text(encoding='utf-8').splitlines()
            self.assertEqual(len(evidence), 1)
            key, old_values, new_values = json.loads(evidence[0])
            self.assertEqual(key, 'undergraduate:class:ABC.A101')
            self.assertEqual(len(old_values), 2)
            self.assertEqual(old_values[1], new_values[1])
            self.assertFalse(shadow.load(output / 'report/reference.json')['documents']['undergraduate']['missedGroups'])

    def test_grade_requires_full_and_page_reviewers_to_agree_with_reference(self):
        key = 'undergraduate:exam:ABC.A101'
        report = {'expected': {key: [[], [['2026-11-25']]]}, 'documents': {}}
        answer = {'changes': [{'id': key, 'before': [], 'after': [['2026-11-25']]}]}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            reference, result = output / 'reference.json', output / 'result.json'
            shadow.save(reference, report)
            for slot in shadow.SLOTS:
                shadow.save(output / f'exam-shadow-answer-{slot}/answer.json', answer)
            self.assertTrue(shadow.grade(reference, output, result))
            shadow.save(output / 'exam-shadow-answer-pages-b/answer.json', {'changes': []})
            self.assertFalse(shadow.grade(reference, output, result))
            self.assertEqual(shadow.load(result)['reviewers']['pages-b']['missing'], [key])
