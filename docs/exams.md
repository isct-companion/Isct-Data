# 試験データの更新

[README](../README.md) · [データ仕様と収録範囲](data.md) · [保守コマンド](maintenance.md) · [試験データの更新](exams.md) · [自動更新の運用](automation.md)

Install dependencies and run the repository-wide checks described in [maintenance.md](maintenance.md).

Run `python3 scripts/validate_exam_feed.py exam/undergraduate/2026-2q.json` and the same command for the graduate feed before publishing. The default checks are feed-wide: source references, IDs, dates, periods/times, status, labels, and malformed room values. Run `python3 scripts/validate_exam_feed.py --check-las-b102 exam/undergraduate/2026-2q.json` only when reviewing the 2026 2Q undergraduate PDF page-16 LAS.B102 regression. The script does not infer class suffixes or alter course matching.

The central exam PDFs cover the rows explicitly published in the public timetable.
Existing manually maintained source records remain available and are updated by
people; the automated workflows do not acquire or modify them.

Exam-only agent instructions are in [`prompts/update-exams.md`](../prompts/update-exams.md). The shared write entry point is `python3 scripts/exam_workflow.py --year 2026 --quarter 2Q --level undergraduate --candidates .exam-runs/reviewed-candidates.json`; run `python3 scripts/exam_workflow.py --check` before and after. The GitHub workflow `.github/workflows/review-exam-candidates.yml` uses that same entry point and emits an exam patch for review. The [scheduled agentic workflow](automation.md) supplies public-source acquisition and Copilot invocation; only public sources are supported by automation.

The source scope and authentication policy are recorded in `source-manifest/2026-2q.json`; candidate files must validate against `schema/exam-candidates.schema.json`. Candidate evidence is a short excerpt with `evidenceHash = SHA-256(UTF-8 evidenceText)`. Automated candidates use public official PDFs. Historical manual-source metadata is retained; login and source acquisition are outside these workflows.

## Exam-week classes

The central exam timetable PDF lists two kinds of rows: 期末試験 (final exams) and
授業 (classes, including make-up classes, held in the exam period). The exam
feed publishes only the first. `exam-week-classes/LEVEL/YEAR-quarter.json`
publishes the second with the exam-feed shape and `kind: "class"`, validated
by `schema/exam-week-classes.schema.json`, and is indexed under
`academicYears.YEAR.examWeekClasses`. Apps that predate the dataset ignore the key.

`scripts/extract_exam_timetable.py` reads the PDF from its table geometry rather
than plain text: grid rules give cells (merged room cells stay whole), thin red
rectangles strike values, a row with a struck course code is withdrawn, and text
right of the table is a margin note. `rows` writes every row for review;
`classes` writes the class feed and refuses when the same PDF's exam rows
disagree with the reviewed exam feed, since that means the PDF changed or the
reader is wrong:

```sh
python3 scripts/exam_workflow.py --year 2026 --quarter 2Q --level undergraduate \
  --candidates .exam-runs/reviewed-candidates.json \
  --timetable-pdf .exam-runs/life-undergraduate-exam-timetable.pdf \
  --retrieved-at 2026-10-24T00:00:00Z
python3 scripts/exam_workflow.py --check
```

A class entry's ID is its slot: course code, date and first period. A moved
session is a new entry. Withdrawn rows are left out.
