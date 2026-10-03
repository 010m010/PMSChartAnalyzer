# PMSChartAnalyzer

- Repository: https://github.com/010m010/PMSChartAnalyzer
- アプリ本体は `pms_analyzer/`、テストは `tests/` にある。文書パスはこの Git ルートを基準とする。
- アプリは Python / PyQt6 製。既存の `.venv` を使い、変更後は `python scripts/check.py` を実行する。セットアップと個別チェックは `docs/development.md` を参照する。

## Agent skills

### Issue tracker

仕様書・作業チケットは `010m010/PMSChartAnalyzer` の GitHub Issues で管理する。Issue を読み書きする前に `docs/agents/issue-tracker.md` を参照する。

### Triage labels

トリアージでは標準の5状態を使う。ラベルの対応と意味は `docs/agents/triage-labels.md` を参照する。

### Domain docs

単一コンテキスト構成を使う。用語・設計判断の読み方と保存先は `docs/agents/domain.md` を参照する。

### UI/UX

画面・図表を変更するときは `ui-ux-pro-max` と `docs/agents/ui-ux.md` を参照し、既存の PyQt6 / matplotlib 構成に適用する。

## サブエージェントの待機

- `wait_agent` を呼ぶたびに、`timeout_ms` には完了までの推定残り時間の2倍をミリ秒で明示する。ツール定義の最短・最大待機時間の範囲に収め、見積もれない場合は既定時間の120000ミリ秒を明示する。通知で途中解除されるため、短い確認のために待機時間を縮めない。タイムアウト後は完了見込みを更新して同じ基準で待つ。
