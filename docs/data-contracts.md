# データ契約と共通の更新経路

CI の Copilot と外部の AI エージェントは、同じ証拠・review・writer・検証・公開バンドルを使用します。
モデルの選択、起動、ツールへの接続、資格情報の管理は実行側の責務です。
モデルごとにデータ形式や合格条件を作りません。

## 契約の正本

- [`contracts/datasets.json`](../contracts/datasets.json): データ種別、ファイル名、schema、年度・版、index の対応と、維持するファイルの収録範囲。
- [`schema/`](../schema/): 各公開形式の必須フィールド、型、列挙値、対応する schemaVersion。
- [`scripts/dataset_contracts.py`](../scripts/dataset_contracts.py): schema を使う共通検証と、ファイル・年度・index・校暦の意味的整合性。
- [`prompts/update-official-data.md`](../prompts/update-official-data.md) と各分野の prompt: 出典の読み方と抽出・レビューの要件。

必須フィールドを prompt に書き直して二重管理しません。契約の変更はコードレビュー対象で、
通常のデータ抽出では変更しません。公開形式の互換性は既存クライアントに対して維持します。

## 同じ処理、異なる実行環境

| 段階 | 共通の処理・成果物 | 実行環境が担当すること |
| --- | --- | --- |
| 取得 | `data_workflow.py --prepare`、取得した bytes・hash・review テンプレート・task.md | Python の実行、ネットワーク環境 |
| 抽出 | 同じ task.md、分野 prompt、`evidence.py`、`.data-runs/review.json` | モデルの起動、ファイルと証拠の提示 |
| 検証・適用 | `--check-review`、`--apply-review`、共通契約、固定 writer | コマンドの実行と診断の返却 |
| 比較・仲裁 | `compare_publications.py`、同じ publication bundle と verdict | 独立モデルの起動が必要なら実行する |
| 公開 | `publish_data.py`、全量検証、対象パスと基準 SHA の確認 | 自動更新 PR の作成、CI、担当者による squash merge |

外部エージェントも、CI と同じ review を書いて同じ writer を使用します。
ローカルでの確認だけなら公開資格情報は不要です。複数作者を使う場合は同じ比較器を呼び、
モデル自身に「一致した」と判定させません。作者同士の一致は正しさの証明ではありません。
片方しか完了しない場合の仲裁や試験のサンプリング方針は [自動更新の運用](automation.md) を参照してください。

## 検証の境界

| Gate | 検証内容 | 検証だけでは分からないこと |
| --- | --- | --- |
| 構造 | schema、必須フィールド、型、日付の形式 | 値が公式資料と一致するか |
| 意味 | ファイル名の年度と内容の一致、試験明細の quarter 一致（既存 exam_workflow）、校暦の日付順序、quarter 内の期間、同じ群の期間の重複、日の重複 | 書かれていない授業や休講を取りこぼしたか |
| 収録・購読 | 契約で要求したファイル、全公開ファイルと index の対応、既存の hash・timestamp 検証 | 宣言していない新年度が公式サイトに登場したか |
| 証拠・公開 | 取得 bytes、review の出典範囲、対象外変更、古い基準 SHA、手動保守データの保護 | モデルの読み違い、出典そのものの誤記 |

`requiredFiles` は維持すべき公開範囲です。ファイルと index を同時に削除しても検出します。
新年度を公開するときは、確認したファイルを契約にも追加します。
単にフォルダーにあるファイルを列挙するだけでは「必要な年度が丸ごとない」を検出できません。

単発の更新では目的のファイルも明示して確認できます。例えば 2027 年度の校暦を要求するなら:

```sh
python scripts/validate_datasets.py --format json --require-file academic-calendar/2027.json
```

まだ公開していなければ、このコマンドは失敗します。通常の CI が通っても、未宣言の 2027 年度まで
収録済みという意味ではありません。将来の年度を日時だけから推測して必須にはしません。
出典が未公開なら、その不足をレビュー結果に明記し、空配列や架空の値で埋めません。

校暦の teachingRanges と examRanges の**相互**排他は現状の gate に含めません。
既存 2026 年度データには両方に属する日があり、その修正には出典との再照合が必要です。
片方の配列内の逆転・重複と、所属 quarter からの逸脱は検証します。

## ローカルと CI の共通コマンド

```sh
python -m pip install -r requirements.txt
python scripts/data_workflow.py --dataset academic-calendar --prepare
# task.md と分野 prompt に従い、証拠を確認して .data-runs/review.json を編集
python scripts/data_workflow.py --dataset academic-calendar --check-review
python scripts/data_workflow.py --dataset academic-calendar --apply-review
python scripts/validate_datasets.py --format json
python scripts/update_subscription_index.py --check
python scripts/exam_workflow.py --check
python -m unittest discover -s tests -v
```

`--check-review` は候補の内容を検証します。新規ファイルはまだ index に存在しないため、
候補段階では公開済み index を要求せず、writer 適用後の全量検証で確認します。
`validate_datasets.py --data-root PATH --format json` は別のデータ checkout を、実行している
検証器側の契約・schema で確認します。診断は code / file / path / message を持ち、
path は JSON Pointer です。AI は診断された箇所を修正し、契約を緩めて通しません。

公開バンドルが必要な実行環境では、変更前の基準コミットを保存し、同じ基準のコードで
`publish_data.py --root PATH --dataset TYPE --base SHA --prepare OUTPUT` を実行します。
CI の publisher は再取得した出典と照合し、公開データに差分がある場合に PR を作成します。
PR では全量 CI を実行し、担当者が出典と差分を確認して squash merge します。

## Skill と MCP

[update-public-data skill](../.agents/skills/update-public-data/SKILL.md) は共通処理を案内する入口です。
スキル自体に別の validator や抽出仕様を持たせません。実行ツールのない AI には、利用者が
このファイルを渡して手順を共有できます。

現時点で専用 MCP サーバーは必要ありません。CLI を実行できないクライアントとの接続が必要になったら、
同じ prepare / evidence / check-review / apply-review / bundle 関数を薄く公開します。
MCP に独自の business logic や model 名による gate を追加しません。公開権限は抽出ツールから分離します。
