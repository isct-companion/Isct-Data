# NAS のデータ更新と検証

[自動更新](automation.md) · [シラバス](courses.md)

`ops/nas-ci/compose.yaml` は 2 つのサービスを起動します。

- `public-data-ci` は GitHub の main を 10 分間隔で確認し、新しいコミットを全量検証します。公開データの更新時刻は [従来の日程](automation.md) と同じ JST です。NAS が停止していた日の更新は同日中に再開したときに実行します。
- `syllabus-reader` は毎日 03:23 JST に動き、1 リクエストずつ取得してファイルの全件再読を輪番します。輪番状態とログは永続ボリュームに保存します。AI は呼び出しません。

GitHub Actions には公開 PR の必須チェック `Validate all datasets` と、main の検証成功後のホームページのデプロイ通知を残します。NAS が取得して実行するコードは公式リポジトリの main です。

## 起動と切替

リポジトリのルートから実行します。Synology の SSH セッションで Docker が PATH にない場合は `/usr/local/bin/docker` を使います。

```sh
cd ops/nas-ci
umask 077
cp -n ci.env.example ci.env
cp -n ../syllabus-reader/.env.example syllabus.env
mkdir -p var/ci var/syllabus/repo var/syllabus/state
docker compose build public-data-ci
docker compose up -d
```

Compose を実行するユーザーとボリュームの所有者が異なる場合は、コンテナの `PUID` と `PGID` を `.env` に設定します。データをチェックアウトの外に置くには、事前に同じディレクトリ構成で `STATE_ROOT` を設定します。

1. この変更を main にマージします。`ci.env` に `OPENAI_API_KEY` と、Isct-Data に限定した `DATA_PR_TOKEN` を設定します。GitHub のトークンには **Contents と Pull requests の read/write** が必要です。`syllabus.env` の `GITHUB_TOKEN` にも同じ権限のトークンを設定します。
2. main の検証と公式ソースの取得を確認します。以下の `--poll-only` はモデルも公開機能も呼び出しません。
3. GitHub のリポジトリ変数 `ISCT_DATA_EXECUTOR` を `nas` に設定し、進行中の旧更新が終わったことを確認します。次に `ci.env` の同じ変数を `nas` に変え、両サービスを `docker compose up -d --force-recreate` で再作成します。

切り戻す場合は、まず NAS の `ci.env` を `ISCT_DATA_EXECUTOR=github` に戻してサービスを再作成し、GitHub の変数を削除します。

## 手動実行

```sh
docker compose run --rm public-data-ci validate
docker compose run --rm public-data-ci update exams --poll-only
docker compose run --rm public-data-ci update exams
docker compose run --rm public-data-ci candidates 2026 2Q undergraduate review/exam-candidates/2026-2q-undergraduate.json
docker compose run --rm public-data-ci shadow /data/state/runs/<run-id>/exam-evidence.zip
docker compose run --rm syllabus-reader --once
```

`update` は `exams`、`academic-calendar`、`important-dates`、`departments` に対応します。`--force` は変更検出と前回の同一ソース判定を省略します。既存の更新 PR が開いている間は保留します。試験の shadow には同一クォーターの 2 版を使い、第 2 引数を省略すると最新の公式 PDF と比較します。候補パッチ、判定、試験ソースのスナップショットは `var/ci/runs/` に 7 日間保存します。

## モデルとトークン

変更が見つかった場合だけ、取得済みの同じ証拠を使って 2 回の Terra レビューを独立して行います。データが一致した場合はコードが採用します。両者が有効で差分があれば、各 Terra は差分だけを相互確認し、Sol が公式出典と突き合わせて選択します。片方だけが有効な場合も既存の仲裁規則で Sol が確認します。固定の比較・書き込み・公開前検証を通して更新 PR を作成します。

全文の添付を避け、証拠は必要な箇所を読み取り専用ツールで取得します。変更なしと検証済みのコミット・出典が同一の場合も再推論を省きます。レビューは low、仲裁は medium で、各レビューのラウンド数とレスポンス出力を制限します。`OPENAI_RUN_TOKEN_LIMIT` は実測の累計を見て次の呼び出しを止める目安です。実行中の 1 リクエストが上限を超える場合があります。Docker ログに入力・キャッシュ入力・出力のトークン数が残ります。
