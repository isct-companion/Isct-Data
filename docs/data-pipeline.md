# Docker によるデータ更新

[自動更新](automation.md) · [シラバス](courses.md)

`ops/data-pipeline/compose.yaml` は 1 つのサービス `isct-data` だけを起動します。1 つのプロセスがすべての定期取得を 1 件ずつ実行し、検証済みの変更を GitHub App で main に公開し、同じプロセスが状態ページを提供します。

| ジョブ | データ | 時刻（JST） | モデル |
| --- | --- | --- | --- |
| `courses` | 開講科目（シラバス、[輪番](courses.md#自動更新)） | 毎日 03:23 | 使わない |
| `exams` | 期末試験と試験週の授業 | 毎日 09:17 | Terra ×2、差分時 Sol |
| `academic-calendar` | 校暦 | 毎日 09:47 | 同上 |
| `important-dates` | 重要日程 | 毎日 10:17 | 同上 |
| `departments` | 学系・履修指南 | 日曜 10:47 | 同上 |

各ジョブは 1 日 1 回です。NAS が止まっていた日は、同じ日のうちに再開した時点で実行します。失敗した回も同じ日には再実行せず、次の予定時刻に最新の main から読み直します。どのジョブも実行のたびに main を取得し、その checkout のスクリプトを使います。イメージに入っているのはスケジューラ（`runner.py`）、モデル呼び出し（`review.py`）、状態ページ（`status.py`）だけです。

公開の前には必須チェック `Validate all datasets` と同じ全量検証を通します。main は GitHub Actions の同じチェックで再検証され、ホームページのデプロイ通知もそこから出ます。

## 起動

リポジトリの checkout の `ops/data-pipeline` で実行します。Synology の SSH セッションで Docker が PATH にない場合は `/usr/local/bin/docker` を使います。

```sh
cd ops/data-pipeline
umask 077
cp -n pipeline.env.example pipeline.env
mkdir -p var/state var/github-app
docker compose up -d --build
```

- `pipeline.env`：OpenAI のキーと GitHub App の ID。シラバスだけならキーは不要です。
- `var/github-app/private-key.pem`：**Contents: Read and write** で Isct-Data だけにインストールした GitHub App の秘密鍵（所有者のみ読み取り可）。公開の直前に短期トークンを発行します。main のルールセットでは、この App だけが必須チェックをバイパスできます。
- `var/state/`：作業用の bare リポジトリ、各回の記録とログ、実行済みの日付、シラバスの輪番状態。Git には入れません。
- `.env`（任意）：`PUID`・`PGID`、データを checkout の外に置く `STATE_ROOT`、状態ページの待ち受けアドレス `STATUS_BIND`。

資格情報が足りないジョブは実行せず、状態ページに「暂停」と理由を表示します。コードの更新は checkout を `git pull` してから `docker compose up -d --build` します。

## 状態ページ

既定では NAS の `http://127.0.0.1:8787/` だけで待ち受けます。ページ自体には認証がないため、外から見る場合はトンネルで公開し、アクセス制御はトンネル側で設定します。トンネルが別のコンテナやホストから回源する場合は、`.env` の `STATUS_BIND` にトンネルが到達できる NAS のアドレス（例：LAN の IP）を一つだけ設定します。`0.0.0.0` にするとすべてのインターフェースに認証なしで公開されます。

| ページ | 内容 |
| --- | --- |
| `/` Overview | 全体の状態（OK・Warning・Critical）とスケジューラの心拍、実行中の回（現在のステップとログ末尾 12 行）、告警の一覧、ジョブごとの行（状態・最後の成功・最新回・次回・30 日間の日ごとの結果・30 日の成功数）、7 日間の集計、最近の 8 回。30 秒ごとに更新します。 |
| `/runs` Runs | ジョブと結果で絞り込める実行一覧（最新 200 件）。 |
| `/jobs/<job>` 任务 | 実行中ならそのログ末尾、そのジョブの告警、30 日間の日ごとの結果、各回の所要時間・リクエスト数・トークン数のグラフ、実行一覧。 |
| `/runs/<run-id>` 运行 | 各ステップ（コマンドと、ソース取得・各レビュー・比較・仲裁）の開始と所要時間、各公式ソースの基線との差（可視内容・バイトのみ・新規・消失・未変更）、2 つのレビューの比較と仲裁、モデル呼び出しごとのトークン、シラバスの読み取り範囲、科目ごとの変化、失敗時のエラーとログ末尾、残っている成果物。実行中はログ末尾 200 行を表示し、5 秒ごとに更新します。 |
| `/courses` 课程轮转 | 各課程ファイルの学院名・科目数・前回詳細ページを読み直した日、30 日間の読み直しと変化の日、最近の課程変化（科目コード・課名・変わった項目）。 |

結果は 已发布・无变化・已检查・保留・失败・中断・进行中 で、色と文字の両方で示します。`/api/status` は Overview の JSON（告警を含む）、`/runs/<run-id>/log` はその回のログ（末尾 1 MiB）、`/runs/<run-id>/files/<path>` は成果物のうちテキストのものです。

### 告警

保守者が対応すべきかどうかは `status.py` の `alerts` だけが判断し、どのページも同じ結果を表示します。

| 級別 | 条件 |
| --- | --- |
| Critical | スケジューラの心拍（`var/state/heartbeat.json`、毎分）が 5 分以上途絶え、実行中の回もない |
| Critical | 1 回の実行が 2 時間を超えている |
| Critical | 資格情報が足りずジョブが暂停している |
| Critical | 最後の成功（已发布・无变化・已检查）から、予定 2 回分と 6 時間が過ぎた（毎日のジョブは 54 時間、学系は 14 日と 6 時間）。または一度も成功していない |
| Critical | 失败または中断を含めて 2 回続けて成功していない |
| Critical | シラバスの科目数が前回の成功から 10% 以上減った（ページ構造の変化を疑う） |
| Warning | 最新回が失败または中断（1 回だけ）。保留だけが 2 回続いた |
| Warning | 最新回で公式ソースが消失した |
| Warning | 最新回のトークン数が `OPENAI_RUN_TOKEN_LIMIT` を超えた |
| Warning | 35 日以上詳細ページを読み直していない課程ファイルがある（輪番は 30 日で一巡） |

保留 1 回だけは告警しません（次の予定時刻に最新の main から読み直す設計どおりの動きです）。`/healthz` は Critical の告警がなければ `200 ok`、あれば `503` と各告警の名前を返すので、外部の死活監視（Uptime Kuma など）からこの URL を監視すれば、NAS ごと止まった場合も含めて通知を受けられます。

各回の記録は `var/state/runs/` に残ります。成果物（試験の証拠、レビュー結果など）は 7 日、`run.log` は 30 日、`status.json` は 180 日で消えます。実行中に再起動した回は「中断」と記録します。

## 手動実行

起動中のコンテナで実行します。定期ジョブと同じロックを使うので、実行中のジョブが終わってから始まります。

```sh
docker compose exec isct-data python /opt/isct/runner.py update exams --poll-only
docker compose exec isct-data python /opt/isct/runner.py update exams
docker compose exec isct-data python /opt/isct/runner.py courses
docker compose exec isct-data python /opt/isct/runner.py courses --full
docker compose exec isct-data python /opt/isct/runner.py candidates 2026 2Q undergraduate review/exam-candidates/2026-2q-undergraduate.json
docker compose exec isct-data python /opt/isct/runner.py shadow /data/state/runs/<run-id>/exam-evidence.zip
```

`update` は `exams`、`academic-calendar`、`important-dates`、`departments` に対応します。`--poll-only` は公式ソースの変更確認だけを行い、モデルも公開も呼び出しません。`--force` は変更検出と前回の同一ソース判定を省略します。`courses --full` はすべてのファイルを全件再読します。試験の shadow には同一クォーターの 2 版を使い、第 2 引数を省略すると最新の公式 PDF と比較します。

## モデルとトークン

公開データに変更が見つかった場合だけ、取得済みの同じ証拠を使って 2 回の Terra レビューを独立して行います。データが一致した場合はコードが採用します。両者が有効で差分があれば、各 Terra は差分だけを相互確認し、Sol が公式出典と突き合わせて選択します。片方だけが有効な場合も既存の仲裁規則で Sol が確認します。固定の比較・書き込み・全量検証に通った変更を main に fast-forward で公開します。検証中に main が進んだ回は「保留」と記録し、次の予定時刻に最新の main から読み直します。

全文の添付を避け、証拠は必要な箇所を読み取り専用ツールで取得します。変更なしと検証済みのコミット・出典が同一の場合も再推論を省きます。レビューは low、仲裁は medium で、各レビューのラウンド数とレスポンス出力を制限します。`OPENAI_RUN_TOKEN_LIMIT` は実測の累計を見て次の呼び出しを止める目安です。実行中の 1 リクエストが上限を超える場合があります。各回のログに入力・キャッシュ入力・出力のトークン数が残ります。モデルのキーはスクリプトには渡しません。

旧 GitHub 更新に切り戻す場合は、[ワークフローの復元手順](../archive/github-actions/README.md) を参照してください。
