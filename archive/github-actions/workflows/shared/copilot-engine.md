---
engine:
  id: copilot
  model: auto
  bare: true
  env:
    GH_AW_NATIVE_COPILOT_AUTO: '1'
  args: [--disable-builtin-mcps, --deny-tool, web_fetch, --deny-tool, web_search, --deny-tool, task]
  harness:
    max-retries: 0
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
---

Shared Copilot engine for the two authors and the arbiter. The token is on a
Copilot Student plan, which only allows native auto model selection (it picks
GPT-5.6 Luna today); a pinned model such as gpt-6-luna is rejected there. Every
agent runs in its own job with its own context.
