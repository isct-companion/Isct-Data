"""Official XHTML must retain its linked evidence when preparing a review."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from check_exam_sources import decode_html
from source_monitor import PublicArtifactLinks, is_html


class OfficialCalendarDiscovery(unittest.TestCase):
    def test_real_calendar_xhtml_discovers_both_schedule_pdfs(self):
        # Unmodified official page downloaded 2026-11-11. Its XML declaration
        # previously prevented snapshot() from discovering the linked PDFs.
        url = 'https://www.titech.ac.jp/student/students/life/schedules'
        content = (ROOT / 'tests/fixtures/academic-calendar-schedules.html').read_bytes()
        self.assertTrue(is_html(content))
        parser = PublicArtifactLinks(url, ('www.titech.ac.jp',))
        parser.feed(decode_html(content))
        self.assertTrue({
            'https://www.titech.ac.jp/student/pdf/life-schedules-month-ay2027.pdf',
            'https://www.titech.ac.jp/student/pdf/life-schedules-week-ay2027.pdf',
        }.issubset(parser.links))
