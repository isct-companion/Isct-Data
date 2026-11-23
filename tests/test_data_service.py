"""The NAS data service: its schedule, its run records and the status pages it serves."""
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ops/data-pipeline"))
import runner
import status
import status_pages as pages

CREDENTIALS = {"ISCT_GITHUB_APP_ID": "1", "ISCT_GITHUB_INSTALLATION_ID": "2", "OPENAI_API_KEY": "k"}


def receipt(runs, name, **record):
    directory = runs / name
    directory.mkdir(parents=True)
    (directory / "status.json").write_text(json.dumps(record), encoding="utf-8")
    return directory


class ScheduleTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        key = Path(directory.name) / "private-key.pem"
        key.write_text("key", encoding="utf-8")
        for patcher in (patch.object(runner, "APP_KEY", key), patch.dict(os.environ, CREDENTIALS)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_each_job_runs_once_a_day_and_catches_up_the_same_day(self):
        monday = datetime(2026, 11, 23, 12, 0, tzinfo=runner.JST)
        plan = runner.upcoming(monday, {"exams": "2026-11-23"})
        self.assertFalse(plan["exams"]["due"])
        self.assertEqual(plan["exams"]["next"], "2026-11-24T09:17+09:00")
        # The NAS was down at 09:47 and 10:17: both run as soon as it is back that day.
        self.assertTrue(plan["academic-calendar"]["due"])
        self.assertTrue(plan["important-dates"]["due"])
        self.assertEqual(plan["courses"]["next"], "2026-11-23T12:00+09:00")
        # Departments are read on Sundays only.
        self.assertFalse(plan["departments"]["due"])
        self.assertEqual(plan["departments"]["next"], "2026-11-29T10:47+09:00")
        early = runner.upcoming(datetime(2026, 11, 29, 9, 0, tzinfo=runner.JST), {})
        self.assertEqual(early["departments"]["next"], "2026-11-29T10:47+09:00")
        self.assertFalse(early["departments"]["due"])

    def test_jobs_pause_without_their_credentials(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            plan = runner.upcoming(datetime(2026, 11, 23, 12, 0, tzinfo=runner.JST), {})
        self.assertEqual(plan["exams"]["paused"], "OPENAI_API_KEY 未配置")
        self.assertFalse(plan["exams"]["due"])
        self.assertIsNone(plan["courses"]["paused"])
        with patch.object(runner, "APP_KEY", Path("missing.pem")):
            self.assertEqual(runner.missing_credentials("courses"), "GitHub App 未配置")


class RunTest(unittest.TestCase):
    def test_each_command_is_a_step_and_a_stale_base_is_a_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            runner.Log.path, runner.Log.record = Path(directory) / "run.log", {}
            self.addCleanup(setattr, runner.Log, "path", None)
            self.addCleanup(setattr, runner.Log, "record", None)

            def say(text):
                return [sys.executable, "-c", f"import sys; print({text!r}, file=sys.stderr); sys.exit(2)"]

            with self.assertRaises(runner.Retry):
                runner.run(directory, *say("data publication failed: main advanced during validation"))
            # The summary holds only the failed command's own lines, not the earlier ones.
            with self.assertRaisesRegex(RuntimeError, r"exited with 2: validation failed: invalid record$"):
                runner.run(directory, *say("validation failed: invalid record"))
            # Work in this process is a named step too, and what it prints reaches the run log.
            stream = runner.Log(open(os.devnull, "w", encoding="utf-8"))
            self.addCleanup(stream.stream.close)
            with patch.object(sys, "stdout", stream), self.assertRaises(ValueError):
                with runner.phase("Sol 仲裁"):
                    print("reviewing")
                    raise ValueError("no verdict")
            steps = json.loads((Path(directory) / "status.json").read_text(encoding="utf-8"))["steps"]
            self.assertEqual([(step["exit"], step.get("phase", False)) for step in steps],
                             [(2, False), (2, False), (None, True)])
            self.assertTrue(steps[0]["command"].startswith("python -c "))
            self.assertIn("reviewing", runner.Log.path.read_text(encoding="utf-8"))

    def test_course_changes_name_each_offering_and_its_changed_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def git(*args):
                subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                               cwd=root, check=True, capture_output=True)

            def write(name, offerings):
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).write_text(json.dumps({"offerings": offerings}, ensure_ascii=False), encoding="utf-8")

            write("courses/2026/a.json", [{"id": "1", "code": "X", "title": {"ja": "甲"}, "credits": 1},
                                          {"id": "2", "code": "Y", "title": {"en": "B"}}])
            write("courses/2026/b.json", [{"id": "3", "code": "Z"}])
            git("init", "-q")
            git("add", "-A")
            git("commit", "-q", "-m", "base")
            base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            write("courses/2026/a.json", [{"id": "1", "code": "X", "title": {"ja": "甲"}, "credits": 2,
                                           "language": "en"}, {"id": "4", "code": "W"}])
            write("courses/2026/c.json", [{"id": "5", "code": "V"}])
            changes = runner.course_changes(root, base)
            self.assertEqual([(change["file"], change["added"], change["removed"], change["changed"])
                              for change in changes],
                             [("courses/2026/a.json", 1, 1, 1), ("courses/2026/c.json", 1, 0, 0)])
            self.assertEqual(changes[0]["items"], [
                {"kind": "added", "id": "4", "code": "W", "title": None},
                {"kind": "removed", "id": "2", "code": "Y", "title": "B"},
                {"kind": "changed", "id": "1", "code": "X", "title": "甲", "fields": ["credits", "language"]},
            ])

    def test_sources_are_compared_with_the_reviewed_baseline(self):
        previous = {"sources": {"a": "1", "b": "1", "c": "1", "gone": "1"}, "content": {"b": "x", "c": "x"}}
        state = {"sources": {"a": "1", "b": "2", "c": "2", "new": "1"}, "content": {"b": "x", "c": "y"}}
        self.assertEqual(runner.source_changes(state, previous), [
            {"url": "a", "change": "same"}, {"url": "b", "change": "bytes"}, {"url": "c", "change": "content"},
            {"url": "new", "change": "new"}, {"url": "gone", "change": "removed"},
        ])
        self.assertEqual(runner.source_changes(state, None)[0]["change"], "new")

    def test_receipts_drop_artifacts_then_logs_then_records_as_they_age(self):
        with tempfile.TemporaryDirectory() as directory:
            runs = Path(directory)
            now = datetime(2026, 11, 23, 12, 0, tzinfo=runner.JST)
            for days in (3, 10, 40, 200):
                folder = runs / f"nas-{now - timedelta(days=days):%Y%m%d-%H%M%S}-0000000{days % 10}"
                (folder / "answers").mkdir(parents=True)
                for name in ("status.json", "run.log", "review-a.json", "answers/x.json"):
                    (folder / name).write_text("{}", encoding="utf-8")
            with patch.object(runner, "RUNS", runs):
                runner.prune(now)
            kept = {folder.name[4:12]: sorted(path.relative_to(folder).as_posix() for path in folder.rglob("*"))
                    for folder in runs.iterdir()}
            self.assertEqual(kept, {
                "20261120": ["answers", "answers/x.json", "review-a.json", "run.log", "status.json"],
                "20261113": ["run.log", "status.json"],
                "20261014": ["status.json"],
            })


NOW = datetime(2026, 11, 23, 12, 0, tzinfo=status.JST)
FAILED_RUN = "nas-20261122-091700-aaaaaaaa"
PUBLISHED_RUN = "nas-20261123-091700-bbbbbbbb"
COURSES_RUN = "nas-20261123-032300-dddddddd"


class StatusPageTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.runs = Path(directory.name) / "runs"
        self.rotation = Path(directory.name) / "courses-rotation.json"
        failed = receipt(
            self.runs, FAILED_RUN, job="exams", status="failed", trigger="schedule",
            startedAt="2026-11-22T09:17:00+09:00", finishedAt="2026-11-22T09:20:00+09:00",
            error="<script>alert(1)</script> exited with 2",
            steps=[{"command": "git fetch", "startedAt": "2026-11-22T09:17:01+09:00", "seconds": 2.0, "exit": 0},
                   {"command": "python scripts/publish_data.py", "startedAt": "2026-11-22T09:17:03+09:00",
                    "seconds": 170.0, "exit": 2}])
        (failed / "run.log").write_bytes(b"$ git fetch\nTraceback: boom\n")
        (failed / "review-a.json").write_text('{"ok": true}', encoding="utf-8")
        (failed / "exam-evidence.zip").write_bytes(b"PK")
        receipt(self.runs, PUBLISHED_RUN, job="exams", status="published", trigger="schedule",
                startedAt="2026-11-23T09:17:00+09:00", finishedAt="2026-11-23T09:40:00+09:00",
                requests=12, tokens=81234, commit="a" * 40, changes=[{"file": "exam/undergraduate/2026-3q.json"}],
                sources=[{"url": "https://www.titech.ac.jp/x.pdf", "change": "content"}],
                review={"authors": ["a", "b"], "same": False, "differences": 3, "arbitrated": True},
                modelCalls=[{"label": "仲裁", "model": "gpt-6.1-sol", "input": 10, "cached": 2, "output": 5,
                             "total": 15}])
        # A receipt from before the runner was one service.
        receipt(self.runs, "nas-20261123-094700-cccccccc", action="update", dataset="academic-calendar",
                status="ok", startedAt="2026-11-23T09:47:00+09:00")
        receipt(self.runs, COURSES_RUN, job="courses", status="published", startedAt="2026-11-23T03:23:00+09:00",
                requests=640, commit="b" * 40,
                courseFiles={"courses/2026/programs.json": 120, "courses/2026/legacy.json": 30},
                years=[{"year": 2026, "files": 2, "offerings": 150, "readInFull": ["courses/2026/programs.json"]}],
                changes=[{"file": "courses/2026/programs.json", "added": 1, "removed": 0, "changed": 1, "items": [
                    {"kind": "added", "id": "202600001", "code": "TCM.B601", "title": "新科目"},
                    {"kind": "changed", "id": "202600002", "code": "TCM.B602", "title": "旧科目",
                     "fields": ["schedule"]}]}])
        self.rotation.write_text(json.dumps({"verified": {"courses/2026/programs.json": "2026-11-23",
                                                          "courses/2026/legacy.json": "2026-10-20"}}))
        self.plan = {"exams": {"next": "2026-11-24T09:17+09:00", "due": False, "paused": None},
                     "courses": {"next": None, "due": False, "paused": "GitHub App 未配置"}}

    def test_overview_cards_and_the_run_filter(self):
        found = status.records(self.runs)
        view = status.overview(found, list(runner.SCHEDULE), self.plan, NOW)
        cards = {card["job"]: card for card in view["cards"]}
        self.assertEqual(list(cards)[:5], list(runner.SCHEDULE))
        self.assertEqual(cards["exams"]["last"]["run"], PUBLISHED_RUN)
        self.assertEqual(cards["exams"]["lastFailure"]["run"], FAILED_RUN)
        self.assertEqual(cards["academic-calendar"]["last"]["status"], "ok")
        self.assertEqual(view["week"], {"runs": 4, "failed": 1, "published": 2, "requests": 652, "tokens": 81234})
        failed = status.overview(found, list(runner.SCHEDULE), self.plan, NOW, job="exams", state="failed")
        self.assertEqual([record["run"] for record in failed["runs"]], [FAILED_RUN])

    def test_history_keeps_each_days_last_result_over_thirty_days(self):
        view = status.history(status.records(self.runs), "exams", self.plan, NOW)
        self.assertEqual(len(view["calendar"]), 30)
        self.assertEqual(view["calendar"][-1]["record"]["run"], PUBLISHED_RUN)
        self.assertEqual(view["calendar"][-2]["record"]["run"], FAILED_RUN)
        self.assertEqual([point["seconds"] for point in view["series"]], [180, 1380])

    def test_course_rotation_lists_oldest_first_with_full_reads_and_changes(self):
        view = status.courses(status.records(self.runs), self.rotation, NOW)
        self.assertEqual([row["file"] for row in view["files"]],
                         ["courses/2026/legacy.json", "courses/2026/programs.json"])
        self.assertEqual(view["files"][1]["reads"], ["2026-11-23"])
        self.assertEqual(view["files"][1]["changed"], ["2026-11-23"])
        self.assertEqual(view["summary"], {"files": 2, "offerings": 150, "covered": 1, "oldest": "2026-10-20",
                                           "unverified": 0})

    def test_pages_escape_run_text_and_show_the_details(self):
        found = status.records(self.runs)
        front = pages.overview(status.overview(found, list(runner.SCHEDULE), self.plan, NOW)).decode()
        self.assertNotIn("<script>", front)
        self.assertIn("&lt;script&gt;", front)
        self.assertIn("暂停：GitHub App 未配置", front)
        failed = pages.detail(status.detail(self.runs, FAILED_RUN)).decode()
        self.assertIn("Traceback: boom", failed)
        self.assertIn("退出码 2", failed)
        self.assertIn(f'href="/runs/{FAILED_RUN}/files/review-a.json"', failed)
        self.assertNotIn("files/exam-evidence.zip", failed)
        published = pages.detail(status.detail(self.runs, PUBLISHED_RUN)).decode()
        for text in ("可见内容有变", "不一致，3 处差异", "gpt-6.1-sol", f'{pages.REPO_URL}/commit/{"a" * 40}'):
            self.assertIn(text, published)
        course = pages.courses(status.courses(found, self.rotation, NOW)).decode()
        self.assertIn("TCM.B602", course)
        self.assertIn("时间与教室", course)
        self.assertIn("每次用时", pages.history(status.history(found, "exams", self.plan, NOW), NOW).decode())

    def test_the_server_serves_pages_logs_and_text_artifacts_only_inside_a_run(self):
        server = status.start(self.runs, self.rotation, list(runner.SCHEDULE), lambda: self.plan, port=0)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        origin = f"http://127.0.0.1:{server.server_address[1]}"
        for path in ("/", "/?job=exams&status=failed", "/jobs/exams", "/courses", f"/runs/{FAILED_RUN}"):
            with urlopen(origin + path) as response:
                self.assertEqual(response.status, 200, path)
        with urlopen(f"{origin}/runs/{FAILED_RUN}/log") as response:
            self.assertEqual(response.read(), b"$ git fetch\nTraceback: boom\n")
        with urlopen(f"{origin}/runs/{FAILED_RUN}/files/review-a.json") as response:
            self.assertEqual(json.load(response), {"ok": True})
        with urlopen(f"{origin}/api/status") as response:
            self.assertEqual(json.load(response)["cards"][1]["last"]["requests"], 12)
        for path in ("/runs/../courses-rotation.json/log", f"/runs/{FAILED_RUN}/files/../../courses-rotation.json",
                     f"/runs/{FAILED_RUN}/files/exam-evidence.zip", "/jobs/nope", f"/runs/{FAILED_RUN}/status.json"):
            with self.assertRaises(HTTPError) as refused:
                urlopen(origin + path)
            self.assertEqual(refused.exception.code, 404, path)


if __name__ == "__main__":
    unittest.main()
