---
imports:
  - copilot-engine.md
tools:
  bash: ["python3:*"]
  edit:
max-turns: 40
max-ai-credits: 20
max-daily-ai-credits: 160
safe-outputs:
  report-failed-jobs: false
  report-failure-as-issue: false
  report-missing-tool: false
  report-missing-data: false
  report-incomplete:
    create-issue: false
steps:
  - uses: actions/setup-python@v5
    with:
      python-version: '3.12'
  - run: python -m pip install -r requirements.txt
  - name: Preserve native Copilot auto selection
    run: python3 scripts/prepare_copilot_auto.py "$RUNNER_TEMP/gh-aw/actions"
  - name: Prepare source evidence and review templates with fixed scripts
    run: python scripts/data_workflow.py --dataset "$DATASET" --prepare
post-steps:
  - name: Validate published data
    run: |
      python scripts/validate_datasets.py
      python scripts/update_subscription_index.py --check
      python scripts/exam_workflow.py --check
  - name: Prepare a scoped publication bundle using immutable base code
    if: success()
    env:
      DATA_BASE_SHA: ${{ github.sha }}
    run: |
      mkdir -p "$RUNNER_TEMP/publication-base" /tmp/gh-aw/publication
      git archive "$DATA_BASE_SHA" scripts | tar -x -C "$RUNNER_TEMP/publication-base"
      python "$RUNNER_TEMP/publication-base/scripts/publish_data.py" --root "$GITHUB_WORKSPACE" \
        --dataset "$DATASET" --base "$DATA_BASE_SHA" --prepare /tmp/gh-aw/publication/publication.json
  - name: Hand the bundle to the independent cross-reviewer
    if: success()
    uses: actions/upload-artifact@v4
    with:
      name: publication-bundle-${{ inputs.slot }}
      path: /tmp/gh-aw/publication/publication.json
      if-no-files-found: error
      retention-days: 7
  - name: Preserve source review evidence
    if: always()
    uses: actions/upload-artifact@v4
    with:
      name: public-source-review-${{ inputs.slot }}
      path: |
        .data-runs/
        .exam-runs/
      retention-days: 7
      include-hidden-files: true
---

Follow `prompts/update-official-data.md`, the domain prompt specified below, and
`.data-runs/task.md`. Evidence is already downloaded, converted to text and
rendered. Do not read PDF binary as text or guess hashed file names.
Edit only the prepared `.data-runs/review.json`. Use only the two fixed writer
commands in the task file to change anything: `--check-review` (writes nothing;
fix what it reports, at most three checks) and then `--apply-review` exactly
once. Read evidence through `python3 scripts/evidence.py` queries or short
read-only Python instead of opening whole files. Do not run git, JSON
formatters or other validation probes. If apply
fails, stop and call report_incomplete; never retry unchanged inputs or invent
flags. When apply succeeds, call `noop` with your source review summary.

You do not publish. Another agent reviews the same evidence independently and
a script compares both results record by record; any disagreement goes to a
third agent. A trusted publisher holding the write credentials then verifies
source bytes, scope, all data checks and main's immutable base before a
non-forced update. Do not create PRs or issues.
