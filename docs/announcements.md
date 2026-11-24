# アプリのお知らせ

[`announcements/v1/announcements.json`](../announcements/v1/announcements.json) は、Isct Companion の「今日」画面の上部に出すお知らせです。
公式情報の自動取得ではなく、メンテナーが PR で直接書きます。形式は [`schema/announcements-v1.schema.json`](../schema/announcements-v1.schema.json)、
意味的な検証は [`scripts/validate_announcements.py`](../scripts/validate_announcements.py) で、CI の `validate-data` が両方を実行します。

## アプリが読むタイミング

アプリはこのファイルを `index.json` を経由せず、raw.githubusercontent.com の `main` から `If-None-Match` 付きで直接取得します。

- アプリが前面にある間（どの画面でも）、前回の確認から 55 分以上たっていれば確認し、開いたままなら 55 分ごとに確認します。
- 手動の更新（「今日」の引き下げ、デスクトップのサイドバーの更新、データ更新の「今すぐ確認」）では間隔に関係なく確認します。
- バックグラウンドでは取得せず、システム通知も出しません。

raw の CDN は 5 分キャッシュするため、マージ後 5 分以内の確認では古い版が返ることがあります。
常に使っている人でも最長でおよそ 1 時間、しばらく開いていなかった人は開いた直後に表示されます。
予定が決まっているお知らせ（メンテナンスなど）は早めに公開して `startsAt` を書けば、その時刻にちょうど表示されます。

## 書き方

```json
{
  "formatVersion": 1,
  "announcements": [
    {
      "id": "2026-12-maintenance",
      "level": "info",
      "startsAt": "2026-12-01T09:00:00+09:00",
      "expiresAt": "2026-12-08T09:00:00+09:00",
      "title": {"ja": "…", "en": "…"},
      "body": {"ja": "…", "en": "…"},
      "platforms": ["ios", "android"],
      "minAppVersion": "1.4.0",
      "link": {"url": "https://www.isct.ac.jp/…", "label": {"ja": "詳細", "en": "Details"}}
    }
  ]
}
```

- `id` は小文字英数字とハイフン。一度使った id は削除後も再利用しません（アプリは閉じた id を覚えています）。
- `level` は `info` か `important`。`important` は目立つ表示になります。
- `startsAt` から `expiresAt` まで表示します。`expiresAt` は必須で、期間は最長 90 日です。
- 本文は改行を含むプレーンテキスト。タイトル 160 バイト、本文 2000 バイト（UTF-8）まで。
- `platforms`（`macos`・`windows`・`ios`・`android`）と `minAppVersion`・`maxAppVersion` は省略すると全員に表示します。
- `link` は `isct.ac.jp` か `isctcomp.app`（とそのサブドメイン）の https URL だけです。
- 取り消すときは項目を削除します。期限切れの項目も削除してかまいません。
- 形式を変えるときは `announcements/v2/` を新しく作り、v1 を読む既存のアプリのために v1 は残します。
