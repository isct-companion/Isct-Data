"""Test the shared contracts against published data and copies with deliberate errors."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from dataset_contracts import DatasetContracts, InvalidContract, read_json

CALENDAR = "academic-calendar/2026.json"


class CandidateContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contracts = DatasetContracts()
        cls.calendar = read_json(ROOT / CALENDAR)

    def test_calendar_keeps_published_versions_and_cross_group_overlaps(self):
        self.assertEqual(self.contracts.validate_candidate("academic-calendar", CALENDAR, self.calendar), [])
        legacy = {k: v for k, v in self.calendar.items() if k not in {"teachingRanges", "examRanges"}}
        legacy["schemaVersion"] = 1
        self.assertEqual(self.contracts.validate_candidate("academic-calendar", CALENDAR, legacy), [])

    def test_candidate_path_year_and_schema_use_json_pointer_errors(self):
        department = read_json(ROOT / "departments/2026.json")
        wrong_year, = self.contracts.validate_candidate("departments", "departments/2027.json", department)
        self.assertEqual((wrong_year.code, wrong_year.file, wrong_year.path),
                         ("dataset.path_value", "departments/2027.json", "/admissionYear"))
        department["admissionYear"] = 2027
        self.assertEqual(self.contracts.validate_candidate("departments", "departments/2027.json", department), [])

        malformed = copy.deepcopy(self.calendar)
        malformed["days"][0]["date"] = "2026-02-30"
        invalid_date, = self.contracts.validate_candidate("academic-calendar", CALENDAR, malformed)
        self.assertEqual((invalid_date.code, invalid_date.path), ("schema.format", "/days/0/date"))

    def test_calendar_relations(self):
        value = copy.deepcopy(self.calendar)
        value["quarters"]["2Q"]["start"] = value["quarters"]["1Q"]["end"]
        value["quarters"]["3Q"]["start"] = "2026-04-02"
        value["quarters"]["4Q"]["end"] = "2027-04-01"
        value["teachingRanges"]["1Q"][1]["start"] = value["teachingRanges"]["1Q"][0]["end"]
        value["teachingRanges"]["3Q"][0]["end"] = "2026-03-31"
        value["examRanges"]["1Q"].reverse()
        value["examRanges"]["4Q"][0]["start"] = "2026-12-02"
        value["days"].append(copy.deepcopy(value["days"][0]))
        value["days"][0]["date"] = "2027-04-01"
        value["days"][1]["date"] = "2027-04-01"
        issues = self.contracts.validate_candidate("academic-calendar", CALENDAR, value)
        self.assertEqual({(issue.code, issue.path) for issue in issues}, {
            ("calendar.quarter_overlap", "/quarters/2Q/start"),
            ("calendar.quarter_order", "/quarters/3Q/start"),
            ("calendar.quarter_outside_year", "/quarters/4Q"),
            ("calendar.segment_overlap", "/teachingRanges/1Q/1/start"),
            ("calendar.range_reversed", "/teachingRanges/3Q/0/end"),
            ("calendar.segment_order", "/examRanges/1Q/1/start"),
            ("calendar.segment_order", "/examRanges/1Q/2/start"),
            ("calendar.segment_outside_quarter", "/examRanges/4Q/0"),
            ("calendar.day_outside_year", "/days/0/date"),
            ("calendar.day_outside_year", "/days/1/date"),
            ("calendar.duplicate_day", "/days/1/date"),
        })

    def test_catalog_schema_requires_index_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("contracts/datasets.json", "schema/dataset-contracts.schema.json"):
                target = root / name
                target.parent.mkdir(exist_ok=True)
                shutil.copy2(ROOT / name, target)
            path = root / "contracts/datasets.json"
            catalog = read_json(path)
            del catalog["datasets"]["academic-calendar"]["index"]
            path.write_text(json.dumps(catalog), encoding="utf-8")
            with self.assertRaises(InvalidContract) as error:
                DatasetContracts(root)
            self.assertEqual(error.exception.issue.code, "schema.required")
            self.assertEqual(error.exception.issue.path, "/datasets/academic-calendar")


class RepositoryContractTests(unittest.TestCase):
    def test_cli_detects_unindexed_and_removed_files_and_requires_requested_year(self):
        with tempfile.TemporaryDirectory() as directory:
            data_root = Path(directory)
            contracts = DatasetContracts()
            for spec in contracts.datasets.values():
                for source in ROOT.glob(spec["glob"]):
                    if source.is_file():
                        target = data_root / source.relative_to(ROOT)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, target)

            index = read_json(ROOT / "index.json")
            del index["academicYears"]["2026"]["classSchedules"]
            del index["admissionYears"]["2025"]
            (data_root / "departments/2025.json").unlink()
            index["academicYears"].get("2027", {}).pop("academicCalendar", None)
            (data_root / "academic-calendar/2027.json").unlink(missing_ok=True)
            (data_root / "index.json").write_text(json.dumps(index), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/validate_datasets.py"), "--data-root", str(data_root),
                 "--format", "json", "--require-file", "academic-calendar/2027.json"],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(result.stderr, "")
            report = json.loads(result.stdout)
            self.assertEqual(report["schemaVersion"], 1)
            self.assertEqual({(issue["code"], issue["file"], issue["path"]) for issue in report["errors"]}, {
                ("dataset.required_file", "academic-calendar/2027.json", ""),
                ("dataset.required_file", "departments/2025.json", ""),
                ("index.source_unlisted", "index.json", "/academicYears/2026/classSchedules"),
            })


if __name__ == "__main__":
    unittest.main()
