---
name: Update exam data
concurrency:
  group: exam-data-update
  cancel-in-progress: false
on:
  schedule:
    - cron: '17 0 * * *'
  workflow_dispatch:
  skip-if-match: 'is:pr is:open in:title "[exam-update]"'
  steps:
    - uses: actions/checkout@v4
      with:
        persist-credentials: false
    - name: Poll public sources without model inference
      id: poll
      run: python3 scripts/check_exam_sources.py
jobs:
  pre-activation:
    outputs:
      changed: ${{ steps.poll.outputs.changed }}
  safe_outputs:
    if: needs.agent.result == 'success'
if: github.event_name == 'workflow_dispatch' || needs.pre_activation.outputs.changed == 'true'
permissions:
  contents: read
  copilot-requests: none
engine:
  id: copilot
  model: auto
network:
  allowed:
    - www.titech.ac.jp
tools:
  bash: true
  edit:
timeout-minutes: 30
max-ai-credits: 50
max-daily-ai-credits: 100
safe-outputs:
  threat-detection:
    max-ai-credits: 15
    continue-on-error: false
    report-as-issue: false
    engine:
      id: copilot
      model: auto
  report-failed-jobs: false
  report-failure-as-issue: false
  report-missing-tool: false
  report-missing-data: false
  report-incomplete:
    create-issue: false
  create-pull-request:
    github-token: ${{ secrets.DATA_PR_TOKEN }}
    github-token-for-extra-empty-commit: none
    title-prefix: '[exam-update] '
    base-branch: main
    draft: true
    fallback-as-issue: false
    protected-files: blocked
    allowed-files:
      - exam/**/*.json
      - exam-week-classes/**/*.json
      - index.json
      - index.sha256
      - review/exam-source-state.json
steps:
  - uses: actions/setup-python@v5
    with:
      python-version: '3.12'
  - run: python -m pip install -r requirements.txt
  - name: Acquire fresh official artifacts for source review
    run: python scripts/check_exam_sources.py
post-steps:
  - name: Validate all published data before safe output processing
    run: |
      python scripts/validate_datasets.py
      python scripts/update_subscription_index.py --check
      python scripts/exam_workflow.py --check
  - name: Preserve acquisition and coverage for review
    if: always()
    uses: actions/upload-artifact@v4
    with:
      name: exam-source-review
      path: .exam-runs/
      retention-days: 14
      include-hidden-files: true
---

Read and follow `prompts/update-exams.md` in full. Review every scope in
`source-manifest/*.json`, undergraduate and graduate separately. The run starts
with fresh public HTML/PDF downloads described in `.exam-runs/acquisition.json`.
Use those exact downloads, their hashes and actual retrieval times; inspect the
landing pages and PDF year/quarter headings before assigning any row to a scope.
The public timetable may still show 2Q while 3Q is pending: retain the 3Q empty
feeds and report `not_yet_published`, never import the 2Q PDF as 3Q data.

Only school source hostname `www.titech.ac.jp` is allowed. The framework adds
its own required GitHub/Copilot transport separately. Do not access LMS, fetch
other hosts, install additional tools, follow off-host redirects, or widen the
allowlist. Record both listed LMS sources and global LMS discovery as coverage
gaps. Do not infer that unlisted LMS courses have no exam.

Use the shared writer `scripts/exam_workflow.py` for every tracked data write.
Evidence, candidates, rendered pages, coverage and reports belong in the ignored
`.exam-runs/` directory. Never hand-edit published feeds, the index or review
state. On a new/revised PDF, run the writer with `--timetable-pdf` so the shared
`extract_exam_timetable.py classes` implementation also updates exam-week classes.
Review drift failures; do not bypass them. Preserve stable assessment identities
and previously reviewed facts when coverage is incomplete.

Only after ALL public source scopes are reviewed (or confirmed not yet
published) and all applicable feed updates pass validation, acknowledge the
snapshot using the writer command documented in the prompt. This deliberately
puts the hash baseline in the same PR as the reviewed facts: it only advances
after human merge, and failed runs keep retrying the change. If review is
incomplete, leave the snapshot untouched and explain the blocker in run artifacts.

Create at most one draft PR through `create_pull_request`. Include fresh source
URLs/hashes, scopes, changed exam/class counts, validation commands, and LMS or
other coverage gaps in its body; a state-only PR is valid when a changed source
was fully reviewed and no published fact changed. Never create issues, comments,
merge a PR, push to main, or publish any other output. If nothing changed, use
noop. A pending `[exam-update]` PR suspends new runs until it is resolved.
