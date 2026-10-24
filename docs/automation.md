# 自動更新と CI の運用

[README](../README.md) · [データ仕様と収録範囲](data.md) · [保守コマンド](maintenance.md) · [試験データの更新](exams.md) · [自動更新の運用](automation.md)

`.github/workflows/validate-data.yml` runs on every PR and every push to `main`
without path filters. Its required-check name is **Validate all datasets**. It
validates all six dataset families (including unindexed files), checks generated
index hashes, runs the exam relational checks and the workflow boundary tests.
Main branch protection requires this GitHub Actions check and a PR, including
for administrators; force pushes and branch deletion are disabled.

`update-exams.md` and its compiled `update-exams.lock.yml` use GitHub Agentic
Workflows v0.93.2. Every day at 09:17 JST (00:17 UTC), the standard-library
`scripts/check_exam_sources.py` hashes public landing pages, manifest PDFs and
currently linked PDFs. It rejects off-host URLs/redirects and failed downloads.
Only a changed fingerprint starts Copilot; manual dispatch forces review. A
pending `[exam-update]` PR pauses further runs. Resolve it to resume polling.
The fingerprint baseline is `review/exam-source-state.json`, written only by
`exam_workflow.py` after complete source review and committed in the generated
PR. First run has no baseline and therefore performs an initial review. Failures
or unmerged PRs never advance main's baseline. No HTTP cache headers or model
claims are used as a substitute for a content hash.

2026 3Q has empty undergraduate/graduate feeds with nonempty provenance and an
empty identity registry. These are publication placeholders, not a claim that
no exams exist. Its manifest deliberately does not reuse quarter-specific 2Q
LMS course IDs. Every run still records global LMS discovery as a coverage gap.
Confirm year/quarter from the actual PDF before publishing; when the official
page still links 2Q, report 3Q as not yet published.

### One-time GitHub setup

- Add **COPILOT_GITHUB_TOKEN** under repository Actions secrets: a fine-grained
  PAT owned by your personal account, with account permission **Copilot
  Requests: read**. This selects your personal subscription entitlements. The
  workflow explicitly disables organization Copilot billing and uses automatic
  model selection for Student compatibility. Your actual remaining credits must
  be checked in your personal Copilot usage settings. It does not purchase extra
  credits. The agent run cap is 50 AI credits (100 per day), with a separate 15-credit
  detection cap; quota failures leave the
  baseline unchanged.
- Add **DATA_PR_TOKEN** as a fine-grained PAT restricted to **Isct-Data**,
  with repository **Contents: read/write** and **Pull requests: read/write**.
  This shared credential can be reused by other dataset update workflows in
  this repository. It is supplied only to the separate safe-output job. The organization currently
  blocks Actions-token PR creation; this repository-scoped user credential
  creates the PR without changing that organization policy. PAT-created PRs
  trigger CI directly, so no additional CI-trigger token is needed. The agent
  itself keeps read-only GitHub credentials. Issue fallback, reporting issues
  and protected-file patches are disabled, and there is no merge output.
- Merge this setup PR before dispatching **Update exam data** from main. Run it
  manually once and review the draft PR, source coverage artifact and CI results.

Official references: [Copilot authentication](https://github.github.com/gh-aw/reference/auth/),
[PR CI triggering](https://github.github.com/gh-aw/reference/triggering-ci/),
[Copilot plans](https://docs.github.com/en/copilot/get-started/plans).

To change the agentic workflow, edit its Markdown source and regenerate the lock:

```sh
gh aw compile update-exams
```

The only school-source network allowlist entry is `www.titech.ac.jp`; required
GitHub/Copilot infrastructure is managed by gh-aw separately. Dependency setup
runs before the agent sandbox starts. Both current exam landing pages and PDF
links use the allowed hostname. A school migration to a different host requires
a reviewed policy/manifest PR, not an automatic allowlist expansion.
