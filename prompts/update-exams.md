# Public exams and exam-week classes

Scope: `exam/` and `exam-week-classes/`, updated together from the same official
PDF. Follow the common public-data review contract first. Existing manually
maintained sources/entries are retained verbatim; this workflow never fetches or
updates them.

Preparation has already inspected actual PDF headings, extracted geometry rows,
rendered pages, and generated candidate files for each public manifest scope.
Read the task and its exact paths; do not guess hashes or PDF names. A scope
the template already marks `confirmed` has an unchanged PDF and no drift from
the published feed; keep it as it is.

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
3. Read the drift report and review the complete prepared candidate list
   against the official PDF. Treat the candidate JSON as read-only. In
   `.data-runs/review.json`, preserve each matching scope's `candidateHash` and
   `candidateCount`. Setting that scope's `confirmed` to true approves exactly
   that list, including an empty list when there is no exam drift. If any fact
   or assessment identity is unresolved, report it and stop without approval.
   The writer regenerates the candidates from the PDF and checks their hash
   before applying the entire approved list.
4. Final-exam rows belong in `exam/`. Ordinary teaching/make-up rows from this same
   PDF belong in `exam-week-classes/`. The fixed batch command invokes
   `exam_workflow.py` with the exact PDF so its shared
   `extract_exam_timetable.py classes` implementation updates both and rejects
   remaining exam drift. The runner runs it after your review; you write nothing.
5. Confirm every public scope in `.data-runs/review.json`, set accurate source
   review scopes and resolve all extraction facts. Only then approve the review.

Call `check` with the complete review (at most three checks), then return it.
The runner then calls `scripts/exam_workflow.py` for all tracked exam writes and
source-state acknowledgement. On a check you cannot fix from the evidence,
return the review with `status: pending` and the unresolved facts. The
independent publisher also re-extracts fresh official PDF rows before
publishing and protects all manual-source records.
