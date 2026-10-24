# 保守コマンド

[README](../README.md) · [データ仕様と収録範囲](data.md) · [保守コマンド](maintenance.md) · [試験データの更新](exams.md) · [自動更新の運用](automation.md)

Python 3.10+ を使用し、依存関係をインストールします。

```sh
python3 -m pip install -r requirements.txt
```

リポジトリのルートで全データを確認します。

```sh
python3 scripts/validate_datasets.py
python3 scripts/update_subscription_index.py --check
python3 scripts/exam_workflow.py --check
python3 -m unittest discover -s tests
```

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

## Course coverage review

`scripts/review_course_coverage.py` requires Python 3.10+ and the downloaded official guide text. It performs review checks without changing data or downloading sources. Prepare UTF-8 text with `pdftotext -layout` as `SOURCE_DIR/YEAR/NN.txt`; `NN` is resolved from each department's actual `guidePdf` filename. Source acquisition and any Japanese OCR remain the agent's responsibility.

```sh
python3 scripts/review_course_coverage.py \
  --data-root . --guides-dir "$RUNNER_TEMP/official-guides" \
  --year 2025 --year 2026 --format json > coverage-review.json
```

For the verified broken Latin mappings in the original 2025 chemistry and transdisciplinary PDFs, add `--shift29 2025:chemistry --shift29 2025:transdisciplinary`. This repair applies only to the explicitly selected sources and preserves layout whitespace. Do not apply it to already decoded or OCR text. Filter a specific review with repeatable `--department ID` arguments.

Exit codes: **0** = no findings, **1** = course-code differences or suspicious titles require agent review, **2** = missing/invalid input. JSON output includes source paths, extraction strategy, missing/extra codes, title findings and input errors. Differences include equivalence and cross-department references; the agent must inspect the official table columns before adding a record. A status of 0 is not proof of complete semantic extraction or official English coverage.

### 既存データの抽出メモ

2025 化学系は PDF 固有の ASCII フォント符号を復号し、47 コードを収録しています。2025 融合理工学系は公式 OCR とページ画像を照合済みです。PDF 変換不能・文字化け・画像表は、公式 PNG/OCR を照合してから登録します。
