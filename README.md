# Isct-Data

Science Tokyo（旧・東京工業大学）の公式情報を、Isct Companion 向けの JSON データとして公開しています。日付は JST です。

## データ

アプリは [`index.json`](index.json) から年度別のデータと更新ハッシュを取得します。各形式は [`schema/`](schema/) を参照してください。

| ディレクトリ | 内容 |
| --- | --- |
| [`academic-calendar/`](academic-calendar/) | 校暦、授業・試験期間、休講日 |
| [`departments/`](departments/) | 学系と標準履修科目 |
| [`important-dates/`](important-dates/) | 行事・入試などの重要日程 |
| [`class-schedules/`](class-schedules/) | 人工保守の個別・隔週授業日程 |
| [`exam/`](exam/) | 学部・大学院の期末試験 |
| [`exam-week-classes/`](exam-week-classes/) | 試験期間中の授業・補講 |

2025・2026 年度を収録しています。試験の公開データは 2026 2Q を収録済みで、3Q は出典付きの空 feed を準備しています。公式の集中試験時間割と LMS 上の個別告知では収録範囲が異なります。空データや未収録は、試験・授業が存在しないことを意味しません。

## ドキュメント

- [データ仕様と収録範囲](docs/data.md) — 各データの意味、出典、既知の欠落
- [保守コマンド](docs/maintenance.md) — 全量検証、購読 index の再生成、履修表の照合
- [試験データの更新](docs/exams.md) — 候補の確認、固定 writer、試験週授業の同時更新
- [自動更新と CI の運用](docs/automation.md) — 種類別 workflow、Copilot、権限と設定
- [エージェント向け指示](prompts/update-official-data.md) · [試験専用指示](prompts/update-exams.md)

## データの誤りを見つけたら

このデータは、公式ページを毎日（学系・履修は毎週）確認する AI の workflow が自動で更新しています。
日付や科目の誤り・欠落に気づいたら、[issue](https://github.com/isct-companion/Isct-Data/issues/new/choose) のフォームで、
該当する項目、現在の値と正しい値、根拠となる公式ページの URL を添えて報告してください。日本語・英語・中国語のどれでもかまいません。

AI に手伝ってもらって書いてもかまいませんが、送信前に内容を読み、自分が確認した事実と一致しているか確かめてください。
条件を満たさない issue は説明なく閉じることがあります。アプリ自体の不具合は[アプリのリポジトリ](https://github.com/isct-companion/isct-companion/issues)へ。

## 公式情報

- [授業日程（2026）](https://www.titech.ac.jp/student/students/life/schedules) · [2025](https://www.titech.ac.jp/student/students/life/schedules/2025)
- [学士課程補講・期末試験](https://www.titech.ac.jp/student/students/life/undergraduate-exam)
- [大学院補講・期末試験](https://www.titech.ac.jp/student/students/life/graduate-exam)
