import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from server import Access, collect, dashboard


class StatusTest(unittest.TestCase):
    def test_signed_access_tokens_are_bound_to_the_application_and_email(self):
        issuer, audience = "https://example.cloudflareaccess.com", "a" * 64
        signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        access = Access(issuer, audience, "author@example.com")
        access.keys = SimpleNamespace(get_signing_key_from_jwt=lambda _: SimpleNamespace(
            key=signing_key.public_key()))
        now = int(time.time())
        claims = dict(iss=issuer, aud=[audience], iat=now, exp=now + 60, email="author@example.com")

        def issue(**changes):
            return jwt.encode(dict(claims, **changes), signing_key, algorithm="RS256")

        self.assertTrue(access.authorizes(issue()))
        self.assertFalse(access.authorizes(issue(email="other@example.com")))
        self.assertFalse(access.authorizes(issue(aud=["another-application"])))
        self.assertFalse(access.authorizes(issue(iss="https://other.cloudflareaccess.com")))
        self.assertFalse(access.authorizes(issue(exp=now - 1)))
        attacker_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.assertFalse(access.authorizes(jwt.encode(claims, attacker_key, algorithm="RS256")))
        self.assertFalse(access.authorizes(""))
        self.assertFalse(Access("", "", "").authorizes(issue()))

    def test_status_view_reads_latest_results_without_returning_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "ci/nas-receipt"
            receipt.mkdir(parents=True)
            (receipt / "status.json").write_text(
                '{"action":"update","dataset":"exams","status":"ok",'
                '"startedAt":"2026-11-23T11:00:00+09:00","untrusted":"private log text"}',
                encoding="utf-8",
            )
            (root / "syllabus.jsonl").write_text(
                '{"startedAt":"2026-11-23T03:23:00+09:00","ok":false,"error":"private log text"}\n',
                encoding="utf-8",
            )
            rows = {row["kind"]: row for row in collect(root)}
            self.assertEqual(rows["exams"]["status"], "ok")
            self.assertEqual(rows["syllabus"]["status"], "failed")
            self.assertEqual(rows["validate"]["status"], "waiting")
            self.assertNotIn(b"private log text", dashboard(rows.values()))


if __name__ == "__main__":
    unittest.main()
