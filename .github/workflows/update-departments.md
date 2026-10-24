---
name: Update departments and course guidance
on:
  schedule:
    - cron: '47 1 * * 0'
  workflow_dispatch:
  steps:
    - uses: actions/checkout@v4
      with:
        persist-credentials: false
    - name: Compare public source fingerprints without inference
      id: poll
      run: python3 scripts/data_workflow.py --dataset "$DATASET" --poll
jobs:
  pre-activation:
    outputs:
      changed: ${{ steps.poll.outputs.changed }}
if: github.event_name == 'workflow_dispatch' || needs.pre_activation.outputs.changed == 'true'
timeout-minutes: 20
permissions:
  contents: read
  copilot-requests: none
imports:
  - shared/public-data.md
env:
  DATASET: departments
network:
  allowed:
    - www.titech.ac.jp
---

This run updates only **departments**. Read `prompts/update-departments.md` in full.
Keep every other dataset and manually maintained source fact unchanged.
