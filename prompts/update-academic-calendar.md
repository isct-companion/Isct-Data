# Academic calendar

Scope: `academic-calendar/YEAR.json`, schema `schema/academic-calendar.schema.json`,
indexed as `academicYears.YEAR.academicCalendar`. Follow the common public-data
review contract first. Calendar years run April through the following March.

- The school's published teaching schedule controls quarters, teaching ranges,
  exam ranges, closure days and campus-specific replacement/no-class overrides.
- Preserve fragmented intervals exactly; never join across a break. Exam ranges
  describe a period, not individual course exams.
- Verify national holidays against the public Cabinet Office source. Only this
  workflow may additionally access `www8.cao.go.jp`; preserve an explicit school
  override on a holiday instead of replacing it with a generic closure.
- Ceremonies, festivals and admissions events belong to `important-dates/`.
  An event does not imply that teaching stops.
- Confirm the academic year from the actual page/PDF. Retain historical editions
  when the current URL moves on; do not rewrite 2026 with 2027 dates.
- Compare every changed day and interval with source text and rendered pages.
  Supply complete reviewed calendar objects in the prepared review's `updates`.
