# Exam-only source-agent run

Start with this Data repository alone, in a fresh checkout. The task is to update
exam data from current official sources. Do not change calendars, curriculum,
class schedules, application code, scripts, schemas or workflow definitions.

1. Read the selected year/quarter source manifest, current exam feed, assessment
   identity registry and candidate schema. Record the current canonical feed hash
   as `baseFeedHash`. Select undergraduate and graduate scopes separately.
2. Visit each applicable official landing page and its current linked artifact.
   Confirm the academic year and quarter from the actual source. For each
   accessible LMS source, verify course identity, including the full class code,
   before extracting assessment facts. A fresh CI runner has no personal login
   session. Record authentication failures as coverage gaps and retain previously
   reviewed records. Repository excerpts are historical evidence, not fresh fetches.
3. Read all exam rows and course assessment notices within the selected scope.
   Compare the fresh source rows with the published exam facts; report the
   reviewed scope and any additions, corrections or gaps. An empty candidate
   array is valid only after that comparison, not as a substitute for acquisition.
   Classify final, quiz, optional oral and other assessments separately. Preserve
   published class suffixes, exact times, allocated periods, rooms and explicit
   cancellations. Do not turn an ordinary teaching row into an exam. Derive an
   end time only from an explicit start and duration; record the derivation.
4. Produce candidate JSON conforming to `schema/exam-candidates.schema.json`.
   Use manifest source IDs and clean source URLs. A candidate's short evidence
   excerpt has `evidenceHash = SHA-256(UTF-8 evidenceText)`. Record actual retrieval
   time and identity/time context. Unresolved or conflicting facts remain
   `confirmed: false`; the merger skips them.
5. Reconcile assessments against the identity registry. Preserve each published
   entry ID. Use `targetEntryId` for an existing legacy record; its identity must
   match the registry. An additional assessment has its own stable `assessmentId`
   and requires `newAssessment: true`. Never use dates as assessment identity.
6. Run the fixed writer from the checkout root:

   ```sh
   python3 scripts/exam_workflow.py --check
   python3 scripts/exam_workflow.py --year YEAR --quarter QUARTER --level LEVEL --candidates REVIEW_FILE
   python3 scripts/exam_workflow.py --check
   ```

   The writer changes only the selected `exam/LEVEL/YEAR-quarter.json`, its index
   reference, and `index.sha256`. Agent evidence and coverage reports stay in the
   run directory. Do not publish, push, or hand-edit other datasets.
7. Write `.exam-runs/coverage.json` with every manifest source's URL, retrieval
   outcome, reviewed scope and unresolved facts. Include inaccessible sources;
   absence from a central timetable is a coverage result, not proof of no exam.
   Write `workflow-result.md` with commands, fresh acquisition results, retained
   historical evidence, validation results and changed paths. If no official fact
   changed, an unchanged feed is a valid result.

The agent owns source interpretation. Schema validation and an evidence hash
check structure and reproducibility; they do not establish a source's truth.
Automated acquisition/model invocation needs a runner with the appropriate
public-network or authorized school-source capability. The GitHub workflow
validates and applies supplied candidates; it does not supply an LMS session.

To reconcile two independent run checkouts:

```sh
python3 scripts/compare_exam_runs.py LEFT_DATA RIGHT_DATA --output reconciliation.json
```

Differences in retrieval timestamps do not count as different exams. Differences
in assessment identity, course code, date, timing, room, status, title or source
URL require review; do not choose the answer by model majority.
