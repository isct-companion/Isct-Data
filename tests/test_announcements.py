"""The announcements gate: the published file passes, and each rule the apps rely on rejects."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from validate_announcements import FILE, issues

NOTICE = {
    "id": "maintenance-notice",
    "level": "info",
    "startsAt": "2026-12-01T09:00:00+09:00",
    "expiresAt": "2026-12-08T09:00:00+09:00",
    "title": {"ja": "お知らせ", "en": "Notice"},
    "body": {"ja": "本文", "en": "Body"},
    "link": {"url": "https://www.isct.ac.jp/", "label": {"ja": "詳細", "en": "Details"}},
}


class AnnouncementTests(unittest.TestCase):
    def test_published_file_passes(self):
        self.assertEqual(issues(json.loads((ROOT / FILE).read_text(encoding="utf-8"))), [])

    def test_each_rule_rejects(self):
        def broken(change):
            item = copy.deepcopy(NOTICE)
            change(item)
            return issues({"formatVersion": 1, "announcements": [item]})

        self.assertEqual(issues({"formatVersion": 1, "announcements": [NOTICE]}), [])
        self.assertEqual(len(issues({"formatVersion": 1, "announcements": [NOTICE, NOTICE]})), 1)
        self.assertTrue(broken(lambda item: item.update(expiresAt=item["startsAt"])))
        self.assertTrue(broken(lambda item: item.update(expiresAt="2027-06-01T09:00:00+09:00")))
        self.assertTrue(broken(lambda item: item.update(minAppVersion="1.5.0", maxAppVersion="1.4.9")))
        self.assertTrue(broken(lambda item: item["title"].update(ja="長" * 60)))
        self.assertTrue(broken(lambda item: item["link"].update(url="https://isct.ac.jp.example.com/")))
        self.assertTrue(broken(lambda item: item["link"].update(url="https://evil.example@isct.ac.jp/")))
        self.assertTrue(broken(lambda item: item["link"].update(url="https://www.isct.ac.jp:443000/")))
        self.assertTrue(broken(lambda item: item.update(expiresAt="2026-02-30T09:00:00+09:00")))
        self.assertTrue(broken(lambda item: item["title"].update(en=" ")))
        self.assertTrue(broken(lambda item: item.pop("expiresAt")))
        self.assertTrue(broken(lambda item: item.update(extra=True)))


if __name__ == "__main__":
    unittest.main()
