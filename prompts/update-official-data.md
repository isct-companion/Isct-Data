# Official data update guidance

Use the current official landing page and linked PDF as the authority for each academic year. Record source title, URL, retrieval timestamp, SHA-256, and PDF page numbers. A newer PDF supersedes an older copy only after checking the landing page and year.

Course extraction rules:

- Treat a department's course-table, standard-plan, or curriculum-map rows as the `recommended` container for published study guidance. Do not infer that an empty extraction means no recommended courses.
- Read each department's own table semantics. Do not use a universal regular expression for group, mark, credits, or content. Only set `mark` when the PDF explicitly marks a course required or recommended; preserve unexplained symbols in `note`.
- Keep the base course code for matching and preserve the full PDF code/suffix in `note`. Store exact Japanese titles and published credits. Omit fields the PDF does not publish; never use zero as a placeholder.
- Parse first, compare extracted codes against the PDF, then visually inspect every difference and wrapped or diagram row. Curriculum-map entries that cannot be matched to a code belong in extraction notes, not invented records.
- A table row may place a wrapped Japanese title above the code line and continue it below; reconstruct the title from the table column and compare code coverage before accepting the row.
- A complete department array must come from the complete published table; adding only a missing-code patch is insufficient. Codes in parentheses or equivalent-course notes are references, not independent rows, unless their own table row has its own title and credits.

Calendar and exam rules:

- Keep teaching and exam intervals fragmented exactly as published; never join across a break. Important events are separate from closure overrides. Add official national holidays and preserve an explicit campus replacement/no-class override on the same date.
- Exam periods are the published period allocation. Do not invent exact minutes. Include only final-exam rows, remove visually struck-through rows, and keep official English titles only where the PDF supplies them.

Localization and completeness:

- Japanese is authoritative. An English translation must be labelled `labelEnglishSource: "translation"`; an official English string is labelled `official`.
- `labelEnglishSource` applies to important-date labels only. Exam `label.en` is copied only when the exam PDF supplies an official English title; do not add that field to exam entries for translations.
- Use the flat public paths (`academic-calendar/2025.json`, `departments/2025.json`, `important-dates/2025.json`, and `exam/{undergraduate,graduate}/2026-2q.json`). Do not create empty files for an unpublished year. Keep unsupported provenance such as hash/retrieval details in a review sidecar until the active schema supports it; never add unknown fields to schema-constrained records.
- Every source must retain the official landing page and artifact URL. Missing historical editions are documented as gaps; they are never represented as a claim that no course or exam exists.
- Resolve each department's guide filename from its stored `guidePdf`; never enumerate a shortened department list to infer PDF numbers. Missing text conversion is a review failure, not a zero-course result. For font-encoded or image PDFs, retain the official PDF and page PNG/OCR evidence, decode only the verified glyph mapping, and visually compare course-code differences before publishing.

Alternating class schedules (`class-schedules/{year}.json`, schema `schema/class-schedules.schema.json`):

- The source is the Schedule PDF a course distributes on LMS (login required); record its pluginfile URL, the course page as `landingPageUrl`, the PDF's own date as `publishedAt`, and its SHA-256. Publish only dates, session kinds, red/white groups and session numbers, never problem sets or other PDF content.
- Copy every dated row of the PDF: `orientation` (both groups), `exercise` or `lab` with its `group`, `exam`, and `no-class` rows (including unnumbered `(*)` rows). A date missing from the PDF is not a class. Never derive a schedule the PDF does not state; a lab needs its own entry from its own schedule.
- Match the entry to syllabus offerings with `offeringIds` for that academic year.
- After editing, recompute the `classSchedules` hash in `index.json` from the canonical JSON (sorted keys, no whitespace, UTF-8).
