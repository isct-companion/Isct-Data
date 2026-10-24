# Public exams and exam-week classes

Scope: `exam/` and `exam-week-classes/`, updated together from the same official
PDF. Follow the common public-data review contract first. Existing manually
maintained sources/entries are retained verbatim; this workflow never fetches or
updates them.

Preparation has already inspected actual PDF headings, extracted geometry rows,
rendered pages, and generated candidate files for each public manifest scope.
Read `.data-runs/task.md` and its exact paths; do not guess hashes or PDF names.

1. Compare each generated scope with the actual PDF year, quarter and level.
   Confirm `not_yet_published` when the PDF still shows an earlier quarter, or
   `different_scope` when a live URL has moved beyond a historical quarter. Never
   import a 2Q PDF into 3Q. Pending feeds retain their nonempty provenance.
2. For a matching PDF, inspect the prepared rows and revisions. If the PDF hash
   matches the previously reviewed provenance AND the geometry comparison has no
   drift, reuse that combined proof instead of loading every unchanged image.
   Otherwise inspect the compact JPEG pages selectively for newly changed facts;
   do not accumulate a whole PDF of images in one model context. A struck
   course-code row is withdrawn. Individual crossed-out values are superseded;
   margin notes are not course titles. Preserve full class suffixes, official
   Japanese/English titles, periods, explicitly stated times and room lists.
   Never invent exact minutes from a period allocation or translate exam titles.
3. Read the drift report against the published public exam rows. When it is empty,
   keep the prepared empty candidate array. When nonempty, review each prepared
   candidate and set `confirmed: true` only for source-confirmed facts. Preserve
   `targetEntryId` for existing assessments and stable `assessmentId` for new
   ones; never use a moved date as assessment identity. Unresolved identities or
   incomplete extraction must stop publication, not guess an answer.
4. Final-exam rows belong in `exam/`. Ordinary teaching/make-up rows from this same
   PDF belong in `exam-week-classes/`. The fixed batch command invokes
   `exam_workflow.py` with the exact PDF so its shared
   `extract_exam_timetable.py classes` implementation updates both and rejects
   remaining exam drift. Do not run separate extraction/write commands yourself.
5. Confirm every public scope in `.data-runs/review.json`, set accurate source
   review scopes and resolve all extraction facts. Only then approve the review.

Run exactly `python3 scripts/data_workflow.py --dataset exams --apply-review`.
This calls `scripts/exam_workflow.py` for all tracked exam writes and source-state
acknowledgement. Do not supply `all`, `full` or `none` as filenames. On any failure,
STOP and report incomplete; repeating the same command cannot repair its inputs.
After success call `publish_data`. The independent publisher also re-extracts
fresh official PDF rows before publishing and protects all manual-source records.
