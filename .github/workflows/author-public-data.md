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
