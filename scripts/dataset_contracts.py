"""Validate reviewed candidates and published datasets against the same contracts."""
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

from dataset_rules import DATASETS, VERSIONED_INDEX
from update_subscription_index import reject_constant
from validate_campus_map import check_content, read_export

ROOT = Path(__file__).resolve().parent.parent
CATALOG = "contracts/datasets.json"
CATALOG_SCHEMA = "schema/dataset-contracts.schema.json"


def pointer(parts):
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts)


@dataclass(frozen=True)
class Issue:
    code: str
    file: str
    path: str
    message: str

    def __str__(self):
        location = f"{self.file} {self.path}" if self.path else self.file
        return f"{location}: [{self.code}] {self.message}"


class InvalidContract(ValueError):
    def __init__(self, issue):
        self.issue = issue
        super().__init__(str(issue))


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)


def check_calendar(name, value):
    issues = []
    year = int(value["academicYear"])
    start, end = f"{year}-04-01", f"{year + 1}-04-01"

    def check_range(current, path, previous, kind):
        if current["start"] > current["end"]:
            issues.append(Issue("calendar.range_reversed", name, f"{path}/end", "End precedes start"))
            return False
        if previous and current["start"] < previous["start"]:
            issues.append(Issue(f"calendar.{kind}_order", name, f"{path}/start", "Start precedes previous start"))
        elif previous and current["start"] <= previous["end"]:
            issues.append(Issue(f"calendar.{kind}_overlap", name, f"{path}/start", "Start overlaps previous range"))
        return True

    previous = None
    quarters = value["quarters"]
    for quarter in ("1Q", "2Q", "3Q", "4Q"):
        bounds = quarters[quarter]
        path = f"/quarters/{quarter}"
        if check_range(bounds, path, previous, "quarter"):
            previous = bounds
            if not start <= bounds["start"] <= bounds["end"] < end:
                issues.append(Issue("calendar.quarter_outside_year", name, path,
                                    f"Quarter must be within academic year {year}"))
    for field in ("teachingRanges", "examRanges"):
        for quarter, ranges in value.get(field, {}).items():
            bounds = quarters[quarter]
            previous = None
            for i, current in enumerate(ranges):
                path = f"/{field}/{quarter}/{i}"
                if not check_range(current, path, previous, "segment"):
                    continue
                if bounds["start"] <= bounds["end"] and (
                    current["start"] < bounds["start"] or current["end"] > bounds["end"]
                ):
                    issues.append(Issue("calendar.segment_outside_quarter", name, path,
                                        f"Range must be within quarter {quarter}"))
                previous = current

    dates = set()
    for i, item in enumerate(value["days"]):
        date = item["date"]
        path = f"/days/{i}/date"
        if date in dates:
            issues.append(Issue("calendar.duplicate_day", name, path, f"Date {date} already occurs in days"))
        if not start <= date < end:
            issues.append(Issue("calendar.day_outside_year", name, path, f"Date must be within academic year {year}"))
        dates.add(date)
    return issues


def check_courses_file(name, value):
    """One course catalog file: its name and group agree, every offering belongs to the year and to
    a unit of this file first, and its periods run forwards."""
    issues = []
    if Path(name).stem != value["group"]["id"]:
        issues.append(Issue("courses.group", name, pointer(("group", "id")), "Group id must match the file name"))
    units = {unit["id"] for unit in value["units"]}
    for i, offering in enumerate(value["offerings"]):
        if not offering["id"].startswith(str(value["academicYear"])):
            issues.append(Issue("courses.year", name, pointer(("offerings", i, "id")),
                                "Offering id must start with the academic year"))
        if offering["units"][0] not in units:
            issues.append(Issue("courses.unit", name, pointer(("offerings", i, "units", 0)),
                                "An offering belongs to the file of the first unit listing it"))
        for j, slot in enumerate(offering["schedule"]):
            if slot["kind"] == "weekly" and slot["periods"][0] > slot["periods"][1]:
                issues.append(Issue("courses.periods", name, pointer(("offerings", i, "schedule", j, "periods")),
                                    "Periods must run forwards"))
    return issues


def check_course_years(paths):
    """Across a year's catalog files: each offering once, and every unit an offering names is listed."""
    issues, years = [], {}
    for name, path in sorted(paths.items()):
        try:
            value = read_json(path)
        except (OSError, ValueError):
            continue  # reported by the per-file check
        if not isinstance(value, dict) or not isinstance(value.get("offerings"), list):
            continue
        year = years.setdefault(value.get("academicYear"), {"units": set(), "offerings": {}, "files": []})
        year["units"].update(unit.get("id") for unit in value.get("units", []) if isinstance(unit, dict))
        year["files"].append((name, value))
    for year in years.values():
        for name, value in year["files"]:
            for i, offering in enumerate(value["offerings"]):
                if not isinstance(offering, dict):
                    continue
                if offering.get("id") in year["offerings"]:
                    issues.append(Issue("courses.duplicate", name, pointer(("offerings", i, "id")),
                                        f"Offering {offering.get('id')} is also in {year['offerings'][offering.get('id')]}"))
                else:
                    year["offerings"][offering.get("id")] = name
                for j, unit in enumerate(offering.get("units") or []):
                    if unit not in year["units"]:
                        issues.append(Issue("courses.unit_missing", name, pointer(("offerings", i, "units", j)),
                                            f"Unit {unit} is not listed in this year's files"))
    return issues


class DatasetContracts:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.validators = {}
        try:
            catalog = read_json(self.root / CATALOG)
        except (OSError, ValueError) as error:
            raise InvalidContract(Issue("contract.read", CATALOG, "", str(error))) from error
        errors = self.schema_issues(CATALOG_SCHEMA, CATALOG, catalog)
        if errors:
            raise InvalidContract(errors[0])
        self.datasets = catalog["datasets"]
        self.patterns = {}
        self.index_groups = {}
        for dataset, spec in self.datasets.items():
            try:
                pattern = re.compile(spec["pathPattern"])
            except re.error as error:
                raise InvalidContract(Issue("contract.path_pattern", CATALOG,
                                            f"/datasets/{dataset}/pathPattern", str(error))) from error
            if pattern.groups != 1:
                raise InvalidContract(Issue("contract.path_pattern", CATALOG, f"/datasets/{dataset}/pathPattern",
                                            "Pattern must capture exactly one index key"))
            self.patterns[dataset] = pattern
            for i, name in enumerate(spec["requiredFiles"]):
                if not pattern.fullmatch(name):
                    raise InvalidContract(Issue("contract.required_file", CATALOG,
                                                f"/datasets/{dataset}/requiredFiles/{i}",
                                                f"Required file {name} does not match its dataset path"))
            group, field = spec["index"]["group"], spec["index"]["field"]
            fields = self.index_groups.setdefault(group, {})
            if field in fields or (fields and (field is None or None in fields)):
                raise InvalidContract(Issue("contract.index_mapping", CATALOG, f"/datasets/{dataset}/index",
                                            "Dataset index mapping conflicts with another dataset"))
            fields[field] = dataset
        self.check_publication_mappings()

    def check_publication_mappings(self):
        # The writer's fixed allowlist is also used when only its scripts were archived.
        for workflow, rules in DATASETS.items():
            group, fields = rules["index"]
            for directory, field in zip(rules["directories"], fields):
                dataset = self.index_groups.get(group, {}).get(field)
                if dataset is not None:
                    spec = self.datasets[dataset]
                    if spec["glob"].split("/", 1)[0] == directory and spec["index"]["multiple"] == (workflow == "exams"):
                        continue
                raise InvalidContract(Issue("contract.index_mapping", CATALOG, "/datasets",
                                            f"Publication scope {workflow} expects {directory} in {group}.{field}"))
        for group, template in VERSIONED_INDEX.items():
            dataset = self.index_groups.get(group, {}).get(None)
            if dataset is not None and not self.datasets[dataset]["index"]["multiple"]:
                files = self.datasets[dataset]["requiredFiles"]
                if all(name == template.format(version=self.patterns[dataset].fullmatch(name)[1]) for name in files):
                    continue
            raise InvalidContract(Issue("contract.index_mapping", CATALOG, "/datasets",
                                        f"Index writer expects {template} in {group}"))

    def schema_issues(self, schema, name, value):
        if schema not in self.validators:
            try:
                definition = read_json(self.root / schema)
                Draft202012Validator.check_schema(definition)
                self.validators[schema] = Draft202012Validator(definition, format_checker=FormatChecker())
            except (OSError, ValueError, SchemaError) as error:
                raise InvalidContract(Issue("contract.schema", schema, "", str(error))) from error
        return [Issue(f"schema.{error.validator}", name, pointer(error.absolute_path), error.message)
                for error in self.validators[schema].iter_errors(value)]

    def validate_candidate(self, dataset, name, value):
        """Validate a parsed replacement object before the workflow updates the index."""
        match = self.patterns[dataset].fullmatch(name)
        if not match:
            return [Issue("dataset.path", name, "", f"Path does not match {dataset} contract")]
        key = match[1]
        spec = self.datasets[dataset]
        issues = self.schema_issues(spec["schema"].replace("{key}", key), name, value)
        if issues:
            return issues
        field = spec["pathValueField"]
        if value.get(field) != int(key):
            issues.append(Issue("dataset.path_value", name, pointer((field,)), f"{field} must match path key {key}"))
        if dataset == "academic-calendar":
            issues.extend(check_calendar(name, value))
        elif dataset == "courses":
            issues.extend(check_courses_file(name, value))
        elif dataset == "campus-map" and not issues:
            messages = []
            check_content(value, messages)
            issues.extend(Issue("campus_map.content", name, "", message) for message in messages[:50])
            if len(messages) > 50:
                issues.append(Issue("campus_map.content", name, "", f"{len(messages) - 50} more content errors"))
        return issues

    def index_references(self, index, present):
        """Check that references resolve to a dataset in the expected index slot."""
        name = "index.json"
        issues, referenced = [], set()
        if not isinstance(index, dict):
            return referenced, [Issue("index.shape", name, "", "Index must be an object")]
        for group in sorted(set(index) - self.index_groups.keys()):
            issues.append(Issue("index.group", name, pointer((group,)), "Unknown dataset group"))
        for group, fields in self.index_groups.items():
            entries = index.get(group, {})
            if not isinstance(entries, dict):
                issues.append(Issue("index.shape", name, pointer((group,)), "Index group must be an object"))
                continue
            for key, entry in entries.items():
                if None in fields:
                    references = {None: entry}
                elif isinstance(entry, dict):
                    references = entry
                else:
                    issues.append(Issue("index.shape", name, pointer((group, key)), "Index entry must be an object"))
                    continue
                for field, references_for_field in references.items():
                    parts = (group, key) if field is None else (group, key, field)
                    dataset = fields.get(field)
                    if dataset is None:
                        issues.append(Issue("index.field", name, pointer(parts), "Unknown dataset field"))
                        continue
                    multiple = self.datasets[dataset]["index"]["multiple"]
                    if multiple and not isinstance(references_for_field, list):
                        issues.append(Issue("index.shape", name, pointer(parts), "References must be an array"))
                        continue
                    references_for_field = references_for_field if multiple else [references_for_field]
                    for i, reference in enumerate(references_for_field):
                        location = (*parts, i) if multiple else parts
                        source = reference.get("source") if isinstance(reference, dict) else None
                        if not isinstance(source, str):
                            issues.append(Issue("index.reference", name, pointer(location),
                                                "Reference must contain a source path"))
                            continue
                        path = pointer((*location, "source"))
                        match = self.patterns[dataset].fullmatch(source)
                        if not match or match[1] != key:
                            issues.append(Issue("index.source_scope", name, path, f"{source} is outside this index slot"))
                        elif source not in present:
                            issues.append(Issue("index.source_missing", name, path, f"Source file {source} does not exist"))
                        elif source in referenced:
                            issues.append(Issue("index.source_duplicate", name, path, f"Source {source} is listed twice"))
                        else:
                            referenced.add(source)
                            if dataset == "campus-map":
                                try:
                                    digest = hashlib.sha256(present[source].read_bytes()).hexdigest()
                                except OSError as error:
                                    issues.append(Issue("dataset.read", source, "", str(error)))
                                    continue
                                if reference.get("hash") != digest:
                                    issues.append(Issue("index.source_hash", name, pointer((*location, "hash")),
                                                        f"Hash does not match {source}"))
        return referenced, issues

    def validate_repository(self, data_root=ROOT, *, required_files=()):
        data_root = Path(data_root).resolve()
        issues, present, expected_index = [], {}, {}
        required = {name for spec in self.datasets.values() for name in spec["requiredFiles"]}
        for name in required_files:
            if any(pattern.fullmatch(name) for pattern in self.patterns.values()):
                required.add(name)
            else:
                issues.append(Issue("dataset.path", name, "", "Required file path does not match a dataset contract"))
        for dataset, spec in self.datasets.items():
            for path in sorted(data_root.glob(spec["glob"])):
                if not path.is_file():
                    continue
                name = path.relative_to(data_root).as_posix()
                if not path.resolve().is_relative_to(data_root):
                    issues.append(Issue("dataset.path", name, "", "Path resolves outside the data root"))
                    continue
                present[name] = path
                match = self.patterns[dataset].fullmatch(name)
                if not match:
                    issues.append(Issue("dataset.path", name, "", f"Path does not match {dataset} contract"))
                    continue
                group, field = spec["index"]["group"], spec["index"]["field"]
                parts = (group, match[1])
                expected_index[name] = pointer((*parts, field) if field else parts)
                try:
                    value = read_export(path) if dataset == "campus-map" else read_json(path)
                except (OSError, EOFError, ValueError) as error:
                    issues.append(Issue("dataset.read", name, "", str(error)))
                    continue
                issues.extend(self.validate_candidate(dataset, name, value))
        issues.extend(check_course_years({name: path for name, path in present.items()
                                          if self.patterns["courses"].fullmatch(name)}))
        for name in sorted(required - present.keys()):
            issues.append(Issue("dataset.required_file", name, "", "Required dataset file is missing"))
        try:
            index = read_json(data_root / "index.json")
        except (OSError, ValueError) as error:
            issues.append(Issue("index.read", "index.json", "", str(error)))
        else:
            referenced, errors = self.index_references(index, present)
            issues.extend(errors)
            for name in expected_index.keys() - referenced:
                issues.append(Issue("index.source_unlisted", "index.json", expected_index[name],
                                    f"Dataset file {name} is missing from the index"))
        return len(present), sorted(issues, key=lambda issue: (issue.file, issue.path, issue.code, issue.message))
