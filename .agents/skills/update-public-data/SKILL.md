---
name: update-public-data
description: Acquire and review Science Tokyo public data in Isct-Data using the shared evidence preparation, data contracts, fixed writers and publication checks. Use for calendar, department, important-date or public exam updates from a local AI agent or CI.
---

# Update Isct-Data public data

Work from the Isct-Data repository root. Read `docs/data-contracts.md`,
`contracts/datasets.json`, `prompts/update-official-data.md` and the selected
`prompts/update-TYPE.md`. These are the shared rules for local agents and CI;
this skill does not define another data format or validation policy.

1. Establish the requested dataset and scope (year, quarter, level). Record the
   starting commit SHA for bundle preparation. Preserve unrelated working changes.
2. Run `python scripts/data_workflow.py --dataset TYPE --prepare`. Read its
   `.data-runs/task.md`. Query downloaded evidence with `scripts/evidence.py`;
   inspect PDF page images when the layout carries meaning. Do not mistake a
   missing source, missing year or empty feed for a confirmed absence of facts.
3. Edit `.data-runs/review.json` using the shared prompt and contract. Keep source
   bytes intact and existing manual-source facts unchanged. If evidence is
   insufficient, report the exact missing scope instead of inventing values.
4. Run the same `--check-review` and `--apply-review` commands as CI. Resolve
   diagnostics against evidence; do not weaken contracts to make a candidate pass.
   If application fails, inspect what was written before attempting recovery.
5. Run the checks in `docs/data-contracts.md`, adding `--require-file` for each
   file the user's requested scope must deliver. Verify the index actually
   references new files, not just that an unindexed JSON file exists.
6. Deliver the diff, evidence coverage and validation result. When publication
   is requested, use the existing PR/CI or trusted publisher route. Bundle
   preparation uses the unchanged base code and the same publication format.
   A successful local validation is not a publication receipt.

For two independent authors, give both the same task and base, then use
`scripts/compare_publications.py --help` for the existing comparison and verdict
flow. Do not implement model-specific merging or average self-reported confidence.
CI may impose additional tool or budget limits; those belong to its runner, not
this data contract. Call runner-specific completion tools only when supplied.
