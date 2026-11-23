# Docker によるデータ更新と検証

[自動更新](automation.md) · [シラバス](courses.md)

`ops/data-pipeline/compose.yaml` は 3 つのサービスを起動します。

- `public-data-ci` は GitHub の main を 10 分間隔で確認し、新しいコミットを全量検証します。公開データの更新時刻は [従来の日程](automation.md) と同じ JST です。NAS が停止していた日の更新は同日中に再開したときに実行します。
- `syllabus-reader` は毎日 03:23 JST に動き、1 リクエストずつ取得してファイルの全件再読を輪番します。輪番状態とログは永続ボリュームに保存します。AI は呼び出しません。
- `status` は両サービスの最新の実行記録を読み取り専用で表示します。設定済みの Cloudflare Access が発行したトークンを検証します。

シラバス取得処理は [`scripts/syllabus_courses.py`](../scripts/syllabus_courses.py)、スケジューラは [`ops/syllabus-reader/runner.py`](../ops/syllabus-reader/runner.py) です。[共通の Compose 構成](../ops/data-pipeline/compose.yaml) で両サービスを管理します。`ops/syllabus-reader/docker-compose.yml` はシラバスだけを実行する構成です。

GitHub Actions には公開 PR の必須チェック `Validate all datasets` と、main の検証成功後のホームページのデプロイ通知を残します。NAS が取得して実行するコードは公式リポジトリの main です。

## 起動と切替

リポジトリのルートから実行します。Synology の SSH セッションで Docker が PATH にない場合は `/usr/local/bin/docker` を使います。

```sh
cd ops/data-pipeline
umask 077
cp -n ci.env.example ci.env
cp -n ../syllabus-reader/.env.example syllabus.env
cp -n status/status.env.example status.env
mkdir -p var/ci/runs var/syllabus/repo var/syllabus/state
touch var/syllabus/state/runs.jsonl
mkdir -m 700 -p var/github-app
docker compose up -d --build
```

Compose を実行するユーザーとボリュームの所有者が異なる場合は、コンテナの `PUID` と `PGID` を `.env` に設定します。データをチェックアウトの外に置くには、事前に同じディレクトリ構成で `STATE_ROOT` を設定します。

実際の `ci.env`、`syllabus.env`、`status.env`、GitHub App の秘密鍵、ローテーション状態、作業用 checkout、ログは運用ホストに保存します。Git には資格情報を空にした設定例を登録します。

1. この変更を main に反映します。`ci.env` の `OPENAI_API_KEY=` に OpenAI のキーを設定します。シラバスには OpenAI のキーは不要です。
2. **Contents: Read and write** の GitHub App を Isct-Data のみにインストールします。秘密鍵は `var/github-app/private-key.pem` に所有者のみ読み取り可能な権限で保存します。両方の環境ファイルに `ISCT_GITHUB_APP_ID`、`ISCT_GITHUB_INSTALLATION_ID`、`ISCT_PUBLICATION_MODE=main` を設定します。NAS は公開の直前に短期トークンを発行します。
3. main の必須チェックをブランチルールセットで管理し、そのチェックだけに NAS の GitHub App をバイパス対象として登録します。強制 push とブランチ削除の拒否は App にも適用します。
4. main の検証と公式ソースの取得を確認します。以下の `--poll-only` はモデルも公開機能も呼び出しません。
5. `ci.env` の `ISCT_DATA_EXECUTOR` を `nas` に設定し、両サービスを `docker compose up -d --force-recreate` で再作成します。

旧 GitHub 更新に切り戻す場合は、[ワークフローの復元手順](../archive/github-actions/README.md) を参照してください。

## 状態ページ

既定の接続先は `http://127.0.0.1:8787` です。別のホストから来る Tunnel に公開する場合は、Compose の `.env` に `STATUS_BIND` を設定して、Tunnel が到達できるホストのアドレスで待ち受けます。

Cloudflare Zero Trust で Self-hosted Access アプリを作成し、One-time PIN と許可するメールアドレスを設定します。`status.env` にチームの発行元 URL、アプリの AUD、カンマ区切りのメールアドレスを入力します。

```dotenv
CF_ACCESS_ISSUER=https://YOUR-TEAM.cloudflareaccess.com
CF_ACCESS_AUDIENCE=YOUR-APPLICATION-AUDIENCE
CF_ACCESS_EMAILS=you@example.com
```

設定変更は `docker compose up -d --force-recreate status` で反映します。`/healthz` は稼働確認用です。状態ページと `/api/status` は Access 設定前に 503 を返します。

## 手動実行

```sh
docker compose run --rm public-data-ci validate
docker compose run --rm public-data-ci update exams --poll-only
docker compose run --rm public-data-ci update exams
docker compose run --rm public-data-ci candidates 2026 2Q undergraduate review/exam-candidates/2026-2q-undergraduate.json
docker compose run --rm public-data-ci shadow /data/state/runs/<run-id>/exam-evidence.zip
docker compose run --rm syllabus-reader --once
```

`update` は `exams`、`academic-calendar`、`important-dates`、`departments` に対応します。`--force` は変更検出と前回の同一ソース判定を省略します。試験の shadow には同一クォーターの 2 版を使い、第 2 引数を省略すると最新の公式 PDF と比較します。候補パッチ、判定、試験ソースのスナップショット、各実行の `status.json` は `var/ci/runs/` に 7 日間保存します。

## モデルとトークン

変更が見つかった場合だけ、取得済みの同じ証拠を使って 2 回の Terra レビューを独立して行います。データが一致した場合はコードが採用します。両者が有効で差分があれば、各 Terra は差分だけを相互確認し、Sol が公式出典と突き合わせて選択します。片方だけが有効な場合も既存の仲裁規則で Sol が確認します。固定の比較・書き込み・全量検証に通った変更を main に fast-forward で公開します。検証中に main が進んだ場合は次の実行で最新の main を取り直します。

全文の添付を避け、証拠は必要な箇所を読み取り専用ツールで取得します。変更なしと検証済みのコミット・出典が同一の場合も再推論を省きます。レビューは low、仲裁は medium で、各レビューのラウンド数とレスポンス出力を制限します。`OPENAI_RUN_TOKEN_LIMIT` は実測の累計を見て次の呼び出しを止める目安です。実行中の 1 リクエストが上限を超える場合があります。Docker ログに入力・キャッシュ入力・出力のトークン数が残ります。
