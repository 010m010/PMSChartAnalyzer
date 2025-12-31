# PMSChartAnalyzer
 PyQt を使った PMS 譜面分析アプリケーションです。9key の .pms / .bms ファイルをドラッグ＆ドロップで読み込み、黒背景の積み上げ棒グラフと各種密度メトリクス（秒間密度、終端秒間密度、平均密度、二乗平均密度、高密度占有率）を表示します。beatoraja 用の難易度表を読み込んで箱ひげ図で密度分布を確認したり、解析履歴を保存することもできます。

## 主な機能
- `.pms` / `.bms` を D&D して解析
- 黒背景の積み上げ棒グラフ（キー別密度）
- 秒間密度（最大）、終端秒間密度（終盤 5 秒平均）、平均密度、二乗平均密度、高密度占有率の表示
- 難易度表（CSV / JSON）を読み込み、難易度別の密度分布を箱ひげ図で表示（URL を保存・再利用可能）
- 解析履歴をローカル (`~/.pms_chart_analyzer`) に保存
- メニューから beatoraja 本体パスを設定可能
- Windows 向けにセットアップ用 `setup.bat` と起動用 `run.bat` を同梱

## 必要環境
- Python 3.10 以上（Windows 10/11 向けを想定）
- 推奨パッケージは `requirements.txt` を参照

## セットアップ
Windows:
```bash
python -m venv .venv
. .venv/Scripts/activate  # PowerShell の場合は .venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
```
macOS / Linux:
```bash
python3 -m venv .venv
source ./.venv/bin/activate
pip install -r requirements.txt
```
もしくは Windows では `setup.bat` を、macOS / Linux では `./setup.sh` を実行してください。

## 使い方
```bash
python main.py
```
Windows では `run.bat` をダブルクリックするだけでも起動できます。macOS / Linux では `./run.sh` を実行してください。
1. 起動後、左側タブの「単曲分析」で .pms / .bms をウィンドウにドラッグ＆ドロップします。
2. 解析が終わると、上部に積み上げ棒グラフ、下部に密度メトリクスが表示されます。
3. 「難易度表」タブでは公開 URL を入力して難易度表を取得し、一括解析と箱ひげ図表示ができます（保存された URL から再選択も可能です）。
4. 「設定」→「beatoraja パスを指定」で beatoraja 本体ディレクトリを登録できます。

### 難易度表フォーマット例
CSV 例（ヘッダー行必須）:
```csv
difficulty,title,pms_path
10,Sample Song,relative/path/to/chart.pms
EX,Another Song,C:\\full\\path\\song.pms
```
JSON 例:
```json
[
  {"difficulty": "10", "title": "Sample Song", "pms_path": "relative/path/to/chart.pms"},
  {"difficulty": "EX", "title": "Another Song", "pms_path": "C:/full/path/song.pms"}
]
```

## Windows 用配布（exe 化）
1. 事前に `pip install pyinstaller` を実行します。
2. 以下を実行して単一フォルダー配布の exe を作成します。
   ```bash
   pyinstaller --name PMSChartAnalyzer --windowed --noconfirm --add-data "requirements.txt;." main.py
   ```
3. `dist/PMSChartAnalyzer/PMSChartAnalyzer.exe` をダブルクリックで起動できます。

## テスト
```bash
pytest
```

## ライセンス
MIT
