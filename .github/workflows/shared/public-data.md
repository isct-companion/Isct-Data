---
concurrency:
  group: public-data-update
engine:
  id: copilot
  model: auto
  bare: true
  env:
    GH_AW_NATIVE_COPILOT_AUTO: '1'
  args: [--disable-builtin-mcps, --deny-tool, web_fetch, --deny-tool, web_search, --deny-tool, task]
  harness:
    max-retries: 0
tools:
  bash: ["python3:*"]
  edit:
max-turns: 40
max-ai-credits: 20
max-daily-ai-credits: 100
safe-outputs:
  threat-detection:
    max-ai-credits: 5
    continue-on-error: false
    report-as-issue: false
    engine:
      id: copilot
      model: auto
      env:
        GH_AW_NATIVE_COPILOT_AUTO: '1'
      args: [--disable-builtin-mcps, --deny-tool, web_fetch, --deny-tool, web_search, --deny-tool, task]
      harness:
        max-retries: 0
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.sha }}
          path: data-runtime
          persist-credentials: false
          sparse-checkout: scripts/prepare_copilot_auto.py
          sparse-checkout-cone-mode: false
      - name: Preserve native Copilot auto selection
        run: python3 data-runtime/scripts/prepare_copilot_auto.py "$RUNNER_TEMP/gh-aw/actions"
  report-failed-jobs: false
  report-failure-as-issue: false
  report-missing-tool: false
  report-missing-data: false
  report-incomplete:
    create-issue: false
  jobs:
    publish-data:
      description: Publish only this workflow's reviewed dataset after independent validation.
      runs-on: ubuntu-latest
      if: needs.agent.result == 'success'
      permissions:
        contents: read
        statuses: write
      artifacts:
        - /tmp/gh-aw/agent/publication.json
      inputs:
        summary:
          description: Source review summary.
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
        - name: Independently validate and publish the scoped data bundle
          env:
            DATA_PR_TOKEN: ${{ secrets.DATA_PR_TOKEN }}
            STATUS_TOKEN: ${{ github.token }}
            DATA_BASE_SHA: ${{ github.sha }}
          run: >-
            python scripts/publish_data.py --dataset "$DATASET" --base "$DATA_BASE_SHA"
            --bundle "$(dirname "$GH_AW_AGENT_OUTPUT")/agent/publication.json"
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
      mkdir -p "$RUNNER_TEMP/publication-base"
      git archive "$DATA_BASE_SHA" scripts | tar -x -C "$RUNNER_TEMP/publication-base"
      python "$RUNNER_TEMP/publication-base/scripts/publish_data.py" --root "$GITHUB_WORKSPACE" \
        --dataset "$DATASET" --base "$DATA_BASE_SHA" --prepare /tmp/gh-aw/agent/publication.json
  - name: Preserve source review evidence
    if: always()
    uses: actions/upload-artifact@v4
    with:
      name: public-source-review
      path: |
        .data-runs/
        .exam-runs/
      retention-days: 7
      include-hidden-files: true
---

Follow `prompts/update-official-data.md`, the domain prompt specified below, and
`.data-runs/task.md`. Evidence is already downloaded, converted to text and
rendered. Do not read PDF binary as text or guess hashed file names.
Edit only the prepared `.data-runs/review.json` and any prepared candidate JSON.
Use only the exact writer command in the task file. Do not run JSON formatting,
validation probes, git diff or other helper commands; the writer validates the review. On its first failure, stop
and call report_incomplete; never retry unchanged inputs or invent flags.
Call publish_data only after that command succeeds. The separate publisher
holds write credentials and verifies source bytes, scope, all data checks and
main's immutable base before a non-forced update. Do not create PRs or issues.
