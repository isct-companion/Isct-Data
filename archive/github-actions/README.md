# 旧 GitHub Actions ワークフロー

定期更新、試験の候補レビューと比較試行、Copilot のワークフローを保存しています。現在の更新は [Docker のデータパイプライン](../../docs/data-pipeline.md) が担当します。GitHub の [全量検証とホームページ通知](../../.github/workflows/validate-data.yml) は稼働しています。

旧更新を復元する場合は、Docker 側の `ci.env` を `ISCT_DATA_EXECUTOR=github` に変更してサービスを再作成します。このディレクトリの `workflows/` と `aw/` をそれぞれ `.github/workflows/` と `.github/aw/` に戻し、旧ワークフローを有効にして GitHub の `ISCT_DATA_EXECUTOR` 変数を削除します。[旧運用の設定](../../docs/automation.md#切り戻し用-github-actions-の設定)
