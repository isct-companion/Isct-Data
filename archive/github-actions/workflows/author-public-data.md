---
name: Author public data review
on:
  workflow_call:
    inputs:
      dataset:
        description: Dataset to review (academic-calendar, departments, important-dates or exams)
        type: string
        required: true
      slot:
        description: Which independent author this is (a or b); keeps the two runs' artifacts apart
        type: string
        required: true
timeout-minutes: 20
# Authors A and B are two calls of this workflow in one run. Give each its own
# groups so they run side by side; a shared group serialized them and once
# cancelled author A while it waited. update-*.yml already runs one dataset at a time.
concurrency:
  group: "public-data-author-${{ inputs.dataset }}-${{ inputs.slot }}-${{ github.run_id }}"
  job-discriminator: "${{ inputs.slot }}-${{ github.run_id }}"
permissions:
  contents: read
  copilot-requests: none
imports:
  - shared/public-data.md
env:
  DATASET: ${{ inputs.dataset }}
network:
  allowed:
    - www.titech.ac.jp
    - www8.cao.go.jp
---

This run updates only **${{ inputs.dataset }}**. Read
`prompts/update-${{ inputs.dataset }}.md` in full.
Keep every other dataset and manually maintained source fact unchanged.
