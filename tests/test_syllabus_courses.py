"""The syllabus reader on saved public syllabus pages, and the course catalog's contract checks."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import syllabus_courses as reader
from dataset_contracts import DatasetContracts, check_course_years

PAGES = ROOT / "tests/fixtures/syllabus"
UNIT = "1-981-400034-0-0"


def page(name):
    return (PAGES / name).read_text(encoding="utf-8")


def listing_entry(offering_id):
    """The listing entry `read_listings` builds for one offering of the saved unit."""
    ja = {row["id"]: row for row in reader.parse_listing(page(f"unit-{UNIT}.ja.html"), 2026, "ja")}
    en = {row["id"]: row for row in reader.parse_listing(page(f"unit-{UNIT}.en.html"), 2026, "en")}
    return {"ja": ja[offering_id], "en": en[offering_id], "units": [UNIT]}


UNITS = [{"school": "0", "unit": UNIT, "level": "program", "name": {"ja": "保存した開講元"}}]


def catalog_file(offerings, group="programs"):
    return {
        "schemaVersion": 1,
        "academicYear": 2026,
        "group": {"id": group, "name": {"ja": "学位プログラム"}},
        "source": [{"id": "syllabus", "url": f"{reader.ORIGIN}/courses/2026"}],
        "units": [{"id": UNIT, "school": "0", "level": "program", "name": {"ja": "保存した開講元"}}],
        "offerings": offerings,
    }


class ReaderTests(unittest.TestCase):
    def test_listings_pair_both_languages_and_refuse_the_wrong_one(self):
        ja = reader.parse_listing(page(f"unit-{UNIT}.ja.html"), 2026, "ja")
        en = reader.parse_listing(page(f"unit-{UNIT}.en.html"), 2026, "en")
        self.assertEqual([row["id"] for row in ja], [row["id"] for row in en])
        self.assertTrue(all(row["code"] == other["code"] for row, other in zip(ja, en)))
        self.assertNotEqual(ja[0]["title"], en[0]["title"])
        # An English page read as the Japanese list (a language redirect gone wrong) stops the run.
        with self.assertRaises(reader.ShapeError):
            reader.parse_listing(page(f"unit-{UNIT}.en.html"), 2026, "ja")

    def test_detail_pages_give_credits_slots_and_rooms_as_printed(self):
        half = reader.parse_detail(page("offering-202607164.html"))
        self.assertEqual([reader.number(amount) for amount in half["credits"]], [0.5, 0.5, 0])
        self.assertEqual(half["class"], "1a(IL1)")
        three = reader.schedule(reader.parse_detail(page("offering-202600077.html"))["schedule"])
        self.assertEqual([(slot["kind"], slot["day"]) for slot in three], [("weekly", 1), ("weekly", 3), ("weekly", 5)])
        self.assertTrue(all(slot["room"] for slot in three))
        intensive, = reader.schedule(reader.parse_detail(page("offering-202601800.html"))["schedule"])
        self.assertEqual(intensive["kind"], "intensive")
        self.assertIn("room", intensive)
        research, = reader.schedule(reader.parse_detail(page("offering-202636055.html"))["schedule"])
        self.assertEqual((research["kind"], research["label"], research["room"]), ("other", "特課研", "各研究室"))
        # A syllabus not written yet has no update date, not a guessed one.
        self.assertIsNone(reader.iso_date(reader.parse_detail(page("offering-202627729.html"))["updated"]))

    def test_record_joins_the_listings_and_the_detail_page(self):
        entry = listing_entry("202623170")
        value = reader.record(2026, entry, reader.parse_detail(page("offering-202623170.html")), UNITS)
        self.assertEqual((value["id"], value["code"], value["quarters"]), ("202623170", "TCM.B601", [1, 2, 3, 4]))
        self.assertEqual(len(value["instructors"]), len(entry["ja"]["instructors"]))
        self.assertTrue(all("en" in name for name in value["instructors"]))
        # The detail page must describe the listed offering.
        other = copy.deepcopy(entry)
        other["ja"]["code"] = "TCM.B602"
        with self.assertRaises(reader.ShapeError):
            reader.record(2026, other, reader.parse_detail(page("offering-202623170.html")), UNITS)

    def test_unknown_shapes_stop_the_run(self):
        for read, text in ((reader.quarters, "通年"), (reader.class_format, "講義 (遠隔型)"),
                           (reader.class_format, "実習"), (reader.schedule, "月1-2-3"), (reader.iso_date, "9月17日")):
            with self.subTest(text=text), self.assertRaises(reader.ShapeError):
                read(text)


class CatalogContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contracts = DatasetContracts()
        entry = listing_entry("202623170")
        cls.offering = reader.record(2026, entry, reader.parse_detail(page("offering-202623170.html")), UNITS)

    def test_a_file_names_its_group_and_holds_only_its_year(self):
        name = "courses/2026/programs.json"
        self.assertEqual(self.contracts.validate_candidate("courses", name, catalog_file([self.offering])), [])
        renamed, = self.contracts.validate_candidate("courses", "courses/2026/legacy.json", catalog_file([self.offering]))
        self.assertEqual(renamed.code, "courses.group")
        stray = dict(self.offering, id="202523170")
        wrong_year, = self.contracts.validate_candidate("courses", name, catalog_file([stray]))
        self.assertEqual((wrong_year.code, wrong_year.path), ("courses.year", "/offerings/0/id"))

    def test_a_year_holds_each_offering_once_and_names_only_listed_units(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory, "a.json"), Path(directory, "b.json")
            first.write_text(json.dumps(catalog_file([self.offering])), encoding="utf-8")
            elsewhere = dict(self.offering, units=[UNIT, "9-999-0-0-0"])
            second.write_text(json.dumps(catalog_file([elsewhere], "legacy")), encoding="utf-8")
            codes = sorted(issue.code for issue in check_course_years({"courses/2026/a.json": first,
                                                                     "courses/2026/b.json": second}))
        self.assertEqual(codes, ["courses.duplicate", "courses.unit_missing"])

    def test_the_index_lists_courses_only_for_a_year_with_a_calendar(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.json").write_text(json.dumps({"academicYears": {"2027": {"importantDates": "x"}},
                                                         "admissionYears": {}}), encoding="utf-8")
            with self.assertRaises(reader.ShapeError):
                reader.list_in_index(root, 2027, {"courses/2027/programs.json": {}})


class RotationTests(unittest.TestCase):
    def test_the_least_recently_verified_files_are_due_up_to_a_share_of_the_offerings(self):
        sizes = {"a": 600, "b": 30, "c": 30, "d": 300}
        verified = {"a": "2026-11-01", "b": "2026-11-20", "c": "2026-10-01"}
        # d was never read in full, so it comes first; it alone covers 960 // 30 = 32 offerings.
        self.assertEqual(reader.due_files(sorted(sizes), sizes, verified), {"d"})
        verified["d"] = "2026-11-21"
        self.assertEqual(reader.due_files(sorted(sizes), sizes, verified), {"c"})
        self.assertEqual(reader.due_files(sorted(sizes), sizes, verified, full=True), set(sizes))

    def test_an_offering_read_only_in_japanese_keeps_its_published_english(self):
        entry = listing_entry("202623170")
        known = reader.record_from_listing(entry, UNITS)
        japanese_only = dict(entry, en=None)
        self.assertEqual(reader.record_from_listing(japanese_only, UNITS, known), known)
        renamed = copy.deepcopy(japanese_only)
        renamed["ja"]["instructors"] = ["別の 教員"]
        self.assertEqual(reader.record_from_listing(renamed, UNITS, known)["instructors"], [{"ja": "別の 教員"}])
        with self.assertRaises(reader.ShapeError):
            reader.record_from_listing(japanese_only, UNITS)


class PublicationTests(unittest.TestCase):
    def test_only_changed_files_make_a_pull_request(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            git = lambda *args: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                                                *args], cwd=root, check=True, capture_output=True)
            git("init", "-q")
            name = "courses/2026/programs.json"
            published = catalog_file([{"id": "202623170", "code": "TCM.B601"}])
            reader.write_year(root, 2026, {name: published})
            for other in ("index.json", "index.sha256"):
                (root / other).write_text("{}\n", encoding="utf-8")
            git("add", "-A")
            git("commit", "-q", "-m", "base")
            base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            reader.write_year(root, 2026, {name: copy.deepcopy(published)})
            self.assertEqual(reader.publication(root, base), {})
            changed = copy.deepcopy(published)
            changed["offerings"][0]["code"] = "TCM.B611"
            reader.write_year(root, 2026, {name: changed})
            self.assertEqual(sorted(reader.publication(root, base)), [name, "index.json", "index.sha256"])
            reader.write_year(root, 2026, {})
            self.assertIsNone(reader.publication(root, base)[name])


if __name__ == "__main__":
    unittest.main()
