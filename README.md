# Isct-Data

Science Tokyo（旧・東京工業大学）の公式情報を、Isct Companion 向けの JSON データとして公開しています。日付は JST です。

## 公開データを利用する

アプリは [`index.json`](index.json) から年度別のデータと更新ハッシュを取得します。各形式は [`schema/`](schema/) を参照してください。

| ディレクトリ | 内容 |
| --- | --- |
| [`academic-calendar/`](academic-calendar/) | 校暦、授業・試験期間、休講日 |
| [`departments/`](departments/) | 学系と標準履修科目 |
| [`important-dates/`](important-dates/) | 行事・入試などの重要日程 |
| [`class-schedules/`](class-schedules/) | 手動で保守する個別・隔週授業日程 |
| [`exam/`](exam/) | 学部・大学院の期末試験 |
| [`exam-week-classes/`](exam-week-classes/) | 試験期間中の授業・補講 |
| [`courses/`](courses/) | 公開シラバス（理工学系）の開講科目カタログ（科目・時間割・教室・単位、形式は [courses.md](docs/courses.md)） |
| [`campus-map/`](campus-map/) | 大岡山・すずかけ台のキャンパスマップ（アプリ用 gzip、形式は [campus-map-export.md](docs/campus-map-export.md)。元データは非公開リポジトリ） |
| [`announcements/`](announcements/) | アプリの「今日」画面に出すお知らせ（手動 PR で保守、index を経由しない。形式は [announcements.md](docs/announcements.md)） |

収録年度と配信ファイルは [`index.json`](index.json) で確認できます。出典、収録範囲、既知の欠落は [データ仕様](docs/data.md) と [試験データの更新](docs/exams.md) を参照してください。未収録の試験・授業は公式情報で確認してください。

## 取得・検証・公開

このリポジトリは公開用の写しです。取得・審査・公開は非公開の運用リポジトリで行い、検証を通ったデータだけをここへ反映します。ここへの直接の変更は反映時に検出され、取り込まれません。誤りの報告は下の issue フォームへお願いします。

| 目的 | 場所 |
| --- | --- |
| 形式と収録範囲を確認する | [`schema/`](schema/) · [`contracts/`](contracts/) · [データ仕様](docs/data.md) · [データ契約](docs/data-contracts.md) |
| 公開データを手元で検証する | [`scripts/validate_datasets.py`](scripts/validate_datasets.py) · [検証ワークフロー](.github/workflows/validate-data.yml) |
| 開講科目カタログの形式を確認する | [シラバスの取得とデータ形式](docs/courses.md) |

## データの誤りを見つけたら

公開データは NAS の定期処理が確認し、検証を通過した差分を公開します。
日付や科目の誤り・欠落に気づいたら、[issue](https://github.com/isct-companion/Isct-Data/issues/new/choose) のフォームで、
該当する項目、現在の値と正しい値、根拠となる公式ページの URL を添えて報告してください。日本語・英語・中国語のどれでもかまいません。

AI に手伝ってもらって書いてもかまいませんが、送信前に内容を読み、自分が確認した事実と一致しているか確かめてください。
条件を満たさない issue は説明なく閉じることがあります。アプリ自体の不具合は[アプリのリポジトリ](https://github.com/isct-companion/isct-companion/issues)へ。

## 公式情報

- [授業日程（2026）](https://www.titech.ac.jp/student/students/life/schedules) · [2025](https://www.titech.ac.jp/student/students/life/schedules/2025)
- [学士課程補講・期末試験](https://www.titech.ac.jp/student/students/life/undergraduate-exam)
- [大学院補講・期末試験](https://www.titech.ac.jp/student/students/life/graduate-exam)
