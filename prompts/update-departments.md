# Departments and course guidance

Scope: `departments/YEAR.json`, schema `schema/departments.schema.json`, indexed
as `admissionYears.YEAR.departments`. YEAR is the student's admission cohort.
Follow the common public-data review contract first.

- Use each department's stored `guidePdf`; never infer PDF numbering from a
  shortened department list. Missing conversion is a review failure.
- Department course tables, standard plans and curriculum maps provide the
  `recommended` container. Empty extraction does not mean no recommended courses.
- Read each table's own column semantics for grouping, marks and credits. Set a
  mark only when explicit; retain unexplained symbols in notes. Never use zero
  as a missing-credit placeholder.
- Match by base course code and preserve the printed full code/suffix in notes.
  Copy exact Japanese titles; join wrapped titles within the same table column.
- Compare complete extracted tables, not just missing-code patches. Parenthetical
  equivalents and cross-department references are not independent recommendations
  unless they have their own titled/credited table row.
- Read the prepared `.data-runs/course-coverage.json` from
  `scripts/review_course_coverage.py` as a mechanical
  cross-check, then inspect all differences and diagram rows visually. Verified
  font repairs and OCR are documented in `docs/maintenance.md`; do not apply a
  font repair to already decoded text. Do not invent official English titles.
- Preserve department identifiers and verify every modified department. Supply
  complete reviewed year objects through the prepared `updates` map.
