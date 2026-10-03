# UI/UX Pro Max

このアプリの UI は PyQt6 と matplotlib で構成されている。UI/UX Pro Max の共通の配色、図表、操作性、アクセシビリティ、タイポグラフィのガイドを、既存の構成に合わせて使う。

PyQt6 は同梱データの `--stack` 対象に含まれていない。PyQt6 の作業では適切な `--domain` で検索し、Qt 固有の実装方法は既存コードと Qt / PyQt の公式資料で確認する。Web 向けのコード例は、そのままデスクトップ UI の実装に置き換えない。

## 検索

Git ルートから、既存の Python 環境で実行する。

```powershell
& '.\.venv\Scripts\python.exe' -B '.\.agents\skills\ui-ux-pro-max\scripts\search.py' 'keyboard focus navigation' --domain ux
& '.\.venv\Scripts\python.exe' -B '.\.agents\skills\ui-ux-pro-max\scripts\search.py' 'time series density distribution' --domain chart
```

検索結果が対象の画面・プラットフォームに合っているか確認する。デザインシステムを保存するときは、Git ルートで検証済みの結果に `--persist --output-dir .` を指定する。既存のデザイン判断は `design-system/` の該当プロジェクトに保存する。
