# Important dates

Scope: `important-dates/YEAR.json`, schema `schema/important-dates.schema.json`,
indexed as `academicYears.YEAR.importantDates`. Follow the common public-data
review contract first.

- Publish explicit dates for orientation, entrance/graduation ceremonies,
  university festivals, homecoming, admissions and other stated events.
- These events do not automatically mean no classes; closure and teaching-day
  overrides belong to the academic calendar workflow.
- Confirm academic year, inclusive start/end dates, category and source identity.
  Keep stable event IDs when an official date is corrected. Do not duplicate an
  event merely because two official pages mention it.
- Japanese is authoritative. Copy official English only where supplied; mark
  English translations with `labelEnglishSource: translation`, and actual
  official English with `official`. This field belongs to important dates only.
- Retain historical events when a live URL rotates to a newer year. Do not invent
  entries for unpublished events or turn missing data into a cancellation.
- Review each changed event against the current public source and provide complete
  reviewed year objects through the prepared `updates` map.
