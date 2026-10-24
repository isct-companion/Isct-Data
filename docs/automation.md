# 公開データの自動更新と CI

[README](../README.md) · [保守コマンド](maintenance.md) · [試験データの更新](exams.md)

| Workflow | データ | 定期チェック（JST） | 個別 prompt |
| --- | --- | --- | --- |
| Update academic calendar | 校暦・授業期間・休講・祝日 | 毎日 09:47 | [校暦](../prompts/update-academic-calendar.md) |
| Update departments and course guidance | 入学年度別の学系・履修指南 | 日曜 10:47 | [学系](../prompts/update-departments.md) |
| Update important dates | 行事・式典・入試の日程 | 毎日 10:17 | [重要日程](../prompts/update-important-dates.md) |
| Update exams and exam-week classes | 期末試験と同じ PDF の授業・補講 | 毎日 09:17 | [試験](../prompts/update-exams.md) |

各 workflow の Markdown には対象、時刻、ネットワーク許可と個別 prompt を指定します。
エンジン、証拠準備、予算、成果物と公開処理は
[shared/public-data.md](../.github/workflows/shared/public-data.md) を共有します。
変更時は対象の Markdown を編集し、`gh aw compile WORKFLOW_NAME` で lock を再生成します。

## 公開までの流れ

1. Python の標準ライブラリで公開ページ、参照 PDF とリンク先 PDF の内容を取得し、SHA-256 を比較します。変更時だけ Copilot を起動し、手動実行はレビューを強制します。
2. 固定スクリプトが証拠のパス、テキスト、PDF ページ画像、レビュー JSON と試験候補を準備します。モデルは対象データの prompt で確認します。
3. モデルは Python と基本的な読み取りツールで証拠を確認し、書き込みには対象の固定レビュー適用コマンドを使います。試験の書き込みは引き続き `exam_workflow.py` が担当し、同じ PDF の試験週授業も同時に更新します。
4. 別ジョブの `publish_data.py` がクリーンな実行基準から変更を適用し、対象パス、他データの index 不変、公開ソースの最新ハッシュ、全量検証とテストを確認します。試験は最新 PDF の行も再照合します。
5. 正確に検証したコミットへ必須の Actions ステータスを記録してから、main を非強制で更新します。途中で main やソースが変われば公開を中止します。

ソース指紋は `review/source-state/TYPE.json` に保存し、試験は既存の
`review/exam-source-state.json` を使用します。検証したデータと同じコミットでのみ進みます。
共通 concurrency により更新実行を直列化します。PR・issue・コメントは生成しません。

エージェントは最大 **40 ターン／20 AI credits**、検出ジョブは **5 credits**、
workflow ごとの過去 24 時間上限は **100 credits** です。harness の自動リトライは無効です。
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
  **Pull requests: read/write** を持ちます。名前は互換性のため維持します。
  使用箇所は独立公開ジョブのみで、モデルへは渡しません。
- main は **Validate all datasets** を GitHub Actions 発行の必須チェックとし、
  管理者にも適用します。PR 前提はなく、強制 push と削除は禁止します。

Copilot CLI は資格情報を保持する AWF proxy を通してネイティブ `/auto` を使います。
固定 gh-aw v0.93.2 の起動処理には SHA-256 検証付きの互換処理を適用します。
BYOK の無指定モデルへのフォールバックを避け、上流 harness が変われば設定を停止します。
組み込み MCP、ネイティブ web ツールと sub-agent は無効にし、明示したツールだけを使います。

## 全量 CI と人工候補の確認

`validate-data.yml` は全 PR と main への全 push で、パスフィルタなしに六種類の
全データ、index、試験の関連整合性と境界テストを確認します。
`review-exam-candidates.yml` は手動で渡した候補のパッチを成果物にする専用入口です。
PR 時の重複した試験専用 CI は全量 CI に統合しました。
