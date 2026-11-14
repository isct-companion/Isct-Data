# 公開データの自動更新と CI

[README](../README.md) · [保守コマンド](maintenance.md) · [試験データの更新](exams.md)

| Workflow | データ | 定期チェック（JST） | 個別 prompt |
| --- | --- | --- | --- |
| Update academic calendar | 校暦・授業期間・休講・祝日 | 毎日 09:47 | [校暦](../prompts/update-academic-calendar.md) |
| Update departments and course guidance | 入学年度別の学系・履修指南 | 日曜 10:47 | [学系](../prompts/update-departments.md) |
| Update important dates | 行事・式典・入試の日程 | 毎日 10:17 | [重要日程](../prompts/update-important-dates.md) |
| Update exams and exam-week classes | 期末試験と同じ PDF の授業・補講 | 毎日 09:17 | [試験](../prompts/update-exams.md) |

`update-*.yml` は対象と時刻だけを指定し、共通の
[public-data-pipeline.yml](../.github/workflows/public-data-pipeline.yml) を呼び出します。
AI 部分は gh-aw の [author-public-data.md](../.github/workflows/author-public-data.md)
（2 回呼ばれる作成者）と [arbitrate-public-data.md](../.github/workflows/arbitrate-public-data.md)
（仲裁者）です。エンジン（Student プランのためネイティブ auto、現在は GPT-5.6 Luna）は
[shared/copilot-engine.md](../.github/workflows/shared/copilot-engine.md)、証拠準備と予算は
[shared/public-data.md](../.github/workflows/shared/public-data.md) が共有します。
Markdown を変更したら `gh aw compile` で lock を再生成します。

## 公開までの流れ

```
triage（スクリプト）─► 作成者 A（AI）─┐
                    └► 作成者 B（AI）─┴► 比較（スクリプト）─一致─────────────────► PR 作成（スクリプト）
                                                └─差分あり─► 仲裁者（AI）─► 統合（スクリプト）─┘
```

1. **triage**: スクリプトが公開ページと PDF を取得し、前回レビュー時と比べます。バイトが同じ、
   またはマークアップだけが変わり表示内容（HTML の本文とリンク、PDF の本文と罫線・取り消し線）が
   同じなら AI を起動しません。手動実行も同じ判定を通り、`force` を指定したときだけ強制します。
2. **作成者 A・B**: 同じ証拠を別々に取得・準備し、互いの結果を見ずにレビューします。
   `--check-review` で書き込みなしに検証し（最大 3 回）、通ったら `--apply-review` を 1 回だけ実行します。
3. **比較**: スクリプトが 2 つの公開バンドルをレコード単位で比較します。ソース指紋か基準コミットが
   違えば中止します。データが一致すればそのまま公開へ進みます。
4. **仲裁者**: 差分があるとき、または片方が完了しなかったときだけ起動します。差分レコードごとに
   A・B・現在の main のどれが証拠と一致するかを選び、根拠を書きます。どれも違えば `none` とし、
   公開しません。片方だけ完了した試験データは、取り消し・削除・出典の変更をすべて確認し、
   新規行はバンドルから決まる乱数で 40 件を抽出して確認します。差分が 150 件を超えると人の確認に回します。
5. **統合**: スクリプトが仲裁者の選択からデータを組み立て、index を再生成し、通常の公開バンドルにします。
6. **PR 作成**: 別ジョブの `publish_data.py` がクリーンな実行基準から変更を適用し、対象パス、他データの
   index 不変、公開ソースの最新ハッシュと全量検証を確認します。試験は最新 PDF の行も再照合します。
   公開データに差分があれば、変更ファイルと公式出典を載せた PR を作成します。出典指紋、取得時刻、
   PDF ハッシュ、index、JSON の整形だけの差分では PR を作りません。
7. **マージ**: PR 上で全量 CI が実行されます。CI が通ったら、試験の日時・教室・取り消しや
   校暦の重要な日付など、利用者に影響する差分を公式出典で確認し、担当者が squash merge します。

ソース指紋は `review/source-state/TYPE.json` に保存し、試験は既存の
`review/exam-source-state.json` を使用します。公開データに差分がない場合、main の指紋は更新しません。
共通 concurrency により更新実行を直列化します。同じデータ種別の自動更新 PR が開いている間は、
その PR のレビューを待ちます。

作成者は 1 回あたり最大 **40 ターン／20 AI credits**（1 回の更新で 2 回）、仲裁者は **40 ターン／20 credits**、
検出ジョブは **5 credits** です。過去 24 時間の上限は作成者 **160**（全データ種類の合計）、仲裁者 **60 credits** です。harness の自動リトライは無効です。
コマンド失敗時は同じ入力で再実行せず、不完全として終了します。
`.data-runs/` と `.exam-runs/` は実行成果物として 7 日間保持します。

## 公開ソースと人工保守の境界

学校の公開ソースは `www.titech.ac.jp` に限定します。校暦 workflow だけ、
国民の祝日のため `www8.cao.go.jp` を追加許可します。URL とリダイレクト先を
スクリプトで検証し、別ホストへの移行を自動承認しません。GitHub/Copilot の
実行基盤通信は gh-aw が別途管理します。

LMS ログイン・取得の機能は提供しません。既存の `class-schedules/2026.json` と
手動ソースを持つ試験記録は保持し、人が更新します。自動公開はこれらの記録・
出典を変更・削除できません。全量 CI は人工保守データも継続検証します。

## GitHub の設定

- `COPILOT_GITHUB_TOKEN`: 個人の fine-grained PAT、**Copilot Requests: read**。
  個人のプランで自動選模し、組織課金権限は使いません。
- `DATA_PR_TOKEN`: Isct-Data だけに限定した既存 PAT。**Contents: read/write** と
  **Pull requests: read/write** を持ちます。専用ジョブがブランチと PR を作成し、
  その PR で通常の Actions CI が起動します。モデルへは渡しません。
- main は **Validate all datasets** を GitHub Actions 発行の必須チェックとし、
  管理者にも適用します。PR のマージ方式は squash のみです。main の強制 push と削除は禁止します。

Copilot CLI は資格情報を保持する AWF proxy を通してネイティブ `/auto` を使います。
固定 gh-aw v0.93.2 の起動処理には SHA-256 検証付きの互換処理を適用します。
BYOK の無指定モデルへのフォールバックを避け、上流 harness が変われば設定を停止します。
組み込み MCP、ネイティブ web ツールと sub-agent は無効にし、明示したツールだけを使います。

## 全量 CI と人工候補の確認

`validate-data.yml` は全 PR と main への全 push で、パスフィルタなしに六種類の
全データ、index、試験の関連整合性と境界テストを確認します。
`review-exam-candidates.yml` は手動で渡した候補のパッチを成果物にする専用入口です。
PR 時の重複した試験専用 CI は全量 CI に統合しました。
