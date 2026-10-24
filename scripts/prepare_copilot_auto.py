#!/usr/bin/env python3
"""Preserve Copilot's native auto selector in the pinned gh-aw v0.93.2 harness."""
import argparse
import hashlib
from pathlib import Path
import sys

# v0.93.2 resolves auto through its generic alias map, selecting a fixed model
# unsupported by Student plans. AWF already passes native Copilot auto through.
# Keep the upstream harness and its security/usage/retry checks; alter only this
# resolver option and CLI-only transport environment, and reject unknown upstream bytes.
ORIGINAL_SHA256 = "ef6e2e1d5cab9d4f77fd70d2a203bc1eae8d4b17a83b9a401f8567e44108acec"
BEFORE = '      role: "main",\n      configuredModel,\n      aliasMap: aliasMap ??'
AFTER = '      role: "main",\n      configuredModel,\n      preserveAuto: true,\n      aliasMap: aliasMap ??'

ENV_BEFORE = '  const childEnv = Object.keys(sdkChildEnv).length > 0 ? buildCopilotEngineChildEnv(process.env, sdkChildEnv) : undefined;'
ENV_AFTER = '  let childEnv = Object.keys(sdkChildEnv).length > 0 ? buildCopilotEngineChildEnv(process.env, sdkChildEnv) : undefined;\n  if (!copilotSDKMode && selectionConfiguredModel === "auto" && process.env.GH_AW_NATIVE_COPILOT_AUTO === "1") {\n    childEnv = buildCopilotEngineChildEnv(process.env, sdkChildEnv);\n    if (!isLikelyAWFAPIProxyURL(childEnv.COPILOT_API_URL) || childEnv.COPILOT_TOKEN !== "ghu_" + "a".repeat(36)) {\n      throw new Error("Native auto requires the existing AWF proxy and its placeholder token");\n    }\n    // Native /auto chooses an entitled model. BYOK /chat/completions with no\n    // model instead uses a legacy server default, which is not CLI auto.\n    for (const key of Object.keys(childEnv)) {\n      if (key.startsWith("COPILOT_PROVIDER_")) delete childEnv[key];\n    }\n    childEnv.COPILOT_OFFLINE = "false";\n  }'


def prepare(path):
    current = path.read_text(encoding='utf-8')
    original = current.replace(AFTER, BEFORE).replace(ENV_AFTER, ENV_BEFORE)
    if hashlib.sha256(original.encode()).hexdigest() != ORIGINAL_SHA256:
        raise ValueError('Unreviewed gh-aw Copilot harness; review the native auto adapter before upgrading')
    if original.count(BEFORE) != 1 or original.count(ENV_BEFORE) != 1:
        raise ValueError('Copilot native auto patch target changed')
    desired = original.replace(BEFORE, AFTER).replace(ENV_BEFORE, ENV_AFTER)
    if current != desired:
        path.write_text(desired, encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("actions_dir", type=Path)
    args = parser.parse_args()
    try:
        prepare(args.actions_dir / "copilot_harness.cjs")
        print("Preserved native Copilot auto selection (gh-aw v0.93.2)")
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
