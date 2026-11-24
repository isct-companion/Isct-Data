# Arbitration contract

Two agents reviewed the same official evidence for one dataset without seeing
each other, and a script found records where their results differ (or one of
them could not finish). You decide each differing record. You have the same
evidence under `.data-runs/` (source text, page images in `.data-runs/pages/`,
and for exams the extracted rows in `.data-runs/exams/`). You have no network
access and need none.

You have read-only tools and no shell: `query` runs `scripts/evidence.py`
(grep across all source text with page numbers, one PDF page's text or tables,
struck-through text on a page, exam rows by course code or date, one record of
a JSON file), `read` reads a slice of a prepared file such as
`.arbiter/comparison.json`, `image` reads a prepared page image, and `check`
validates a draft verdict. Use targeted queries: page images and big JSON files
cost far more than a query.

For every item in `.arbiter/comparison.json`:

1. Read its `options`: `a` and `b` are the two authors' versions, `main` is what
   is published today. `null` means the record does not exist in that version.
2. Find the fact in the source yourself. Do not prefer an option because two
   versions agree, because it is newer, or because it is more detailed.
3. Pick the option that matches the source exactly: dates, periods, times,
   rooms, titles, codes, categories, year, quarter and level. Labels are copied,
   never translated or invented. Struck-through PDF rows or values are withdrawn
   or superseded; margin notes are not titles. Missing or unpublished material
   is not proof that a record does not exist, so prefer `main` over a deletion
   the source does not state.
4. Write `evidence`: the file and page, heading or line that proves the choice.
5. If no option matches the source, choose `none` and say what the source says.
   Nothing is published then, and a person looks at it. That is a correct
   outcome; never pick an option you could not confirm.

Fill the verdict template (`.arbiter/verdict.json`) and call `check` with the
complete verdict JSON. It writes nothing; fix only what it lists, at most three
checks. Then return the verdict JSON with a short `summary` of what you decided.
A trusted script builds the final data from your choices, and the publisher
re-validates everything before main changes.
