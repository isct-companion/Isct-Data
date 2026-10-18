# Isct-Data

公開データは Science Tokyo（旧・東京工業大学）の公式ページと公式PDFから抽出しています。日付は JST です。

## 公式入口

- 授業日程（2026）: https://www.titech.ac.jp/student/students/life/schedules
- 授業日程（2025）: https://www.titech.ac.jp/student/students/life/schedules/2025
- 学士課程補講・期末試験: https://www.titech.ac.jp/student/students/life/undergraduate-exam
- 大学院補講・期末試験: https://www.titech.ac.jp/student/students/life/graduate-exam

## カバレッジ

- 2025: 校暦と学部入学者用学科データ。公式の年度別試験時間割アーカイブは確認できなかったため、試験データは未収録です。未掲載は試験が存在しないことを意味しません。
- 2026: 校暦、学部・大学院の公式 2Q 期末試験時間割（授業行を除外し、視覚確認で取り消し線の旧行を除外）。

重要日程（入学式、学位記授与式、ホームカミングデイ、大学祭、入試等）は `important-dates/` に独立収録しています。重要日程は休講を意味せず、休講情報は校暦の `days` に記録します。

公開ファイルは年度単位のフラットなパス（`academic-calendar/2025.json`、`departments/2025.json`、`important-dates/2025.json`）です。試験は `exam/undergraduate/2026-2q.json` と `exam/graduate/2026-2q.json` に収録しています。

試験PDFは公式入口の更新版を取得し、各エントリに出典ページを記録しています。時限はPDFの割当（例: 3-4）で、正確な開始・終了時刻は推測していません。

隔週授業の日程は `class-schedules/2026.json` に収録しています。物理学演習・物理学実験は赤組・白組が隔週で交互に受講し、各回が赤・白・全員のどれに当たるかは公開シラバスではなく、LMS の科目ページで配布される Schedule PDF にしか載っていません。各エントリは `offeringIds`（シラバスの講義 ID）で科目に対応付け、`sessions` に PDF の全日付（オリエンテーション、演習、試験、休講）を記録します。2026 年度は物理学演習第二 English Class（3〜4Q）のみ収録済みで、他クラスと物理学実験は未収録です。未収録のクラスはアプリで毎週表示され、「隔週・日程未収録」と表示されます。

校暦の `teachingRanges` は通常授業の分段、`examRanges` は公式校暦が示す期末試験・補講期間です。`examRanges` は個別科目の試験一覧ではなく、休業期間や試験日を通常授業として誤表示しないための期間情報です。

試験データではPDFに記載された英語科目名を `label.en` にそのまま収録しています。試験PDFに開始・終了時刻の記載がないため、`periods` のみを使用しています。

入学案内の付表・標準履修例からコースコードを抽出し、2025/2026 の全学系ファイルへ収録しています。コード差集で他系科目・共通科目の参照が混在する箇所は `scripts/review_course_coverage.py` の出力を人手確認中です。2025化学系はPDF固有のASCIIフォント符号を復号済み、2025融合理工学系は公式OCRとページ画像を照合済みです。空配列は「推薦科目なし」を意味しません。
2025化学系は47コード、2025融合理工学系はOCR確認した公式付表行を収録済みです。PDF変換不能・文字化け・画像表は、公式PNG/OCRを照合してから登録します。空配列は「推薦科目なし」を意味しません。

## Workflow review CLI

`scripts/review_course_coverage.py` requires Python 3.10+ and the downloaded official guide text. It performs review checks without changing data or downloading sources. Prepare UTF-8 text with `pdftotext -layout` as `SOURCE_DIR/YEAR/NN.txt`; `NN` is resolved from each department's actual `guidePdf` filename. Source acquisition and any Japanese OCR remain the agent's responsibility.

```sh
python3 scripts/review_course_coverage.py \
  --data-root . --guides-dir "$RUNNER_TEMP/official-guides" \
  --year 2025 --year 2026 --format json > coverage-review.json
```

For the verified broken Latin mappings in the original 2025 chemistry and transdisciplinary PDFs, add `--shift29 2025:chemistry --shift29 2025:transdisciplinary`. This repair applies only to the explicitly selected sources and preserves layout whitespace. Do not apply it to already decoded or OCR text. Filter a specific review with repeatable `--department ID` arguments.

Exit codes: **0** = no findings, **1** = course-code differences or suspicious titles require agent review, **2** = missing/invalid input. JSON output includes source paths, extraction strategy, missing/extra codes, title findings and input errors. Differences include equivalence and cross-department references; the agent must inspect the official table columns before adding a record. A status of 0 is not proof of complete semantic extraction or official English coverage.

## Exam-feed extraction check

Install the validator dependency with `python3 -m pip install -r requirements.txt`.

Run `python3 scripts/validate_exam_feed.py exam/undergraduate/2026-2q.json` and the same command for the graduate feed before publishing. The default checks are feed-wide: source references, IDs, dates, periods/times, status, labels, and malformed room values. Run `python3 scripts/validate_exam_feed.py --check-las-b102 exam/undergraduate/2026-2q.json` only when reviewing the 2026 2Q undergraduate PDF page-16 LAS.B102 regression. The script does not infer class suffixes or alter course matching.

The central exam PDFs are a public concentrated-exam source. They cover rows published in the undergraduate or graduate final-exam timetable, not every assessment announced inside an LMS course. An authorized source agent may publish a course-specific final assessment from an authenticated LMS page when it has a clean course/forum URL and a confirmed normalized fact. Publish only the minimum v1 fields and provenance; keep full forum posts, links containing session state, credentials, student identity, and unrelated classroom instructions out of this repository. Unconfirmed or conflicting candidates remain in the review sidecar.

Exam-only agent instructions are in [`prompts/update-exams.md`](prompts/update-exams.md). The shared write entry point is `python3 scripts/exam_workflow.py --year 2026 --quarter 2Q --level undergraduate --candidates review/lms-candidates/2026-2q.json`; run `python3 scripts/exam_workflow.py --check` before and after. The GitHub workflow `.github/workflows/exams.yml` uses that same entry point and emits an exam patch for review. It validates supplied candidates; model invocation and authenticated source acquisition remain runner responsibilities.

The source scope and authentication policy are recorded in `source-manifest/2026-2q.json`; candidate files must validate against `schema/exam-candidates.schema.json`. Candidate evidence is a short excerpt with `evidenceHash = SHA-256(UTF-8 evidenceText)`. The manifest allows public official PDFs and authorized LMS facts, while session cookies and credentials remain outside the repository.

## Subscription index

After changing any published JSON dataset, regenerate its canonical JSON hash,
publication timestamp, and the lightweight plain-text index hash:

```sh
python3 scripts/update_subscription_index.py
```

The app discovers datasets through `index.json` and hashes that response locally.
`index.sha256` remains generated repository metadata. CI can verify generated
files without modifying them:

```sh
python3 scripts/update_subscription_index.py --check
```
