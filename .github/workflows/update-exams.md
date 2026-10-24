---
name: Update exam data
concurrency:
  group: exam-data-update
  cancel-in-progress: false
on:
  schedule:
    - cron: '17 0 * * *'
  workflow_dispatch:
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
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.sha }}
          path: exam-runtime
          persist-credentials: false
          sparse-checkout: scripts/prepare_copilot_auto.py
          sparse-checkout-cone-mode: false
      - name: Preserve native Copilot auto selection
        run: python3 exam-runtime/scripts/prepare_copilot_auto.py "$RUNNER_TEMP/gh-aw/actions"
  report-failed-jobs: false
  report-failure-as-issue: false
  report-missing-tool: false
  report-missing-data: false
  report-incomplete:
    create-issue: false
  jobs:
    publish-exam-data:
      description: Publish the reviewed exam data directly to main after independent validation.
      runs-on: ubuntu-latest
      if: needs.agent.result == 'success'
      permissions:
        contents: read
        statuses: write
      artifacts:
        - /tmp/gh-aw/agent/exam-publication.json
      inputs:
        summary:
          description: Brief source review and coverage summary for this publication.
          required: true
          type: string
      steps:
        - uses: actions/checkout@v4
          with:
            ref: ${{ github.sha }}
            persist-credentials: false
        - uses: actions/setup-python@v5
          with:
            python-version: '3.12'
        - run: python -m pip install -r requirements.txt
        - name: Independently validate and publish the data-only bundle
          env:
            DATA_PR_TOKEN: ${{ secrets.DATA_PR_TOKEN }}
            STATUS_TOKEN: ${{ github.token }}
            EXAM_BASE_SHA: ${{ github.sha }}
          run: >-
            python scripts/publish_exam_update.py --base "$EXAM_BASE_SHA"
            --bundle "$(dirname "$GH_AW_AGENT_OUTPUT")/agent/exam-publication.json"

steps:
  - uses: actions/setup-python@v5
    with:
      python-version: '3.12'
  - run: python -m pip install -r requirements.txt
  - name: Preserve native Copilot auto selection
    run: python3 scripts/prepare_copilot_auto.py "$RUNNER_TEMP/gh-aw/actions"
  - name: Acquire fresh official artifacts for source review
    run: python scripts/check_exam_sources.py
post-steps:
  - name: Validate all published data before safe output processing
    run: |
      python scripts/validate_datasets.py
      python scripts/update_subscription_index.py --check
      python scripts/exam_workflow.py --check
  - name: Prepare a bounded data-only publication bundle
    if: success()
    env:
      EXAM_BASE_SHA: ${{ github.sha }}
    run: |
      git show "$EXAM_BASE_SHA:scripts/publish_exam_update.py" > "$RUNNER_TEMP/prepare-exam-publication.py"
      python "$RUNNER_TEMP/prepare-exam-publication.py" --root "$GITHUB_WORKSPACE" \
        --base "$EXAM_BASE_SHA" --prepare /tmp/gh-aw/agent/exam-publication.json
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
puts the hash baseline in the same atomic data commit as the reviewed facts:
it only advances after the trusted publisher succeeds, and failed runs retry. If review is
incomplete, leave the snapshot untouched and explain the blocker in run artifacts.

When every source scope has been reviewed and the writer has finished, call
`publish_exam_data` with a brief review summary. This signals the separate trusted
publisher; the agent cannot push or merge. It accepts only exam feeds, exam-week
class feeds, their index metadata and the reviewed source fingerprint. It checks
the exact run base, complete source coverage and fresh source hashes, reruns all
validation and boundary tests, records the required GitHub Actions status on the
candidate commit, and updates main only by fast-forward. If main or source bytes
changed during review, publication fails for a fresh run. Do not create PRs,
issues, comments, or change any other repository files. If no update is needed,
call noop instead. Keep detailed review results in `.exam-runs/` artifacts.
