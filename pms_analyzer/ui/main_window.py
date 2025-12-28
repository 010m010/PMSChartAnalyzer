from __future__ import annotations

import traceback
from pathlib import Path
from typing import Dict, List, Optional
from statistics import mean

from PyQt6.QtCore import QEvent, QThread, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QDragEnterEvent, QDropEvent, QDragMoveEvent
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpacerItem,
    QSizePolicy,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QComboBox,
    QAbstractItemView,
    QSplitter,
)
import requests

from ..analysis import DensityResult, compute_density
from ..difficulty_table import (
    ChartAnalysis,
    DifficultyTable,
    analyze_table,
    find_song_in_db,
    load_difficulty_table_from_content,
)
from ..pms_parser import PMSParser
from ..storage import (
    AnalysisRecord,
    add_saved_table,
    append_history,
    get_saved_tables,
    load_config,
    save_config,
    remove_saved_table,
)
from .charts import BoxPlotCanvas, DifficultyScatterChart, StackedDensityChart


def _mean(values: List[float | int]) -> float:
    return mean(values) if values else 0.0


def _quantiles(values: List[float]) -> Dict[str, float | None]:
    if not values:
        return {"min": None, "q1": None, "median": None, "q3": None, "max": None, "mean": None}
    sorted_vals = sorted(values)
    n = len(sorted_vals)

    def _percentile(p: float) -> float:
        if n == 1:
            return sorted_vals[0]
        k = (n - 1) * p
        f = int(k)
        c = min(f + 1, n - 1)
        return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)

    return {
        "min": sorted_vals[0],
        "q1": _percentile(0.25),
        "median": _percentile(0.5),
        "q3": _percentile(0.75),
        "max": sorted_vals[-1],
        "mean": mean(sorted_vals),
    }


class AnalysisWorker(QThread):
    finished = pyqtSignal(object, object)
    failed = pyqtSignal(str)

    def __init__(self, parser: PMSParser, path: Path):
        super().__init__()
        self.parser = parser
        self.path = path

    def run(self) -> None:  # type: ignore[override]
        try:
            result = self.parser.parse(self.path)
            density = compute_density(result.notes, result.total_time)
            self.finished.emit(result, density)
        except Exception:  # noqa: BLE001
            self.failed.emit(traceback.format_exc())


class DifficultyTableWorker(QThread):
    finished = pyqtSignal(object, object)
    failed = pyqtSignal(str)

    def __init__(self, parser: PMSParser, table_source: str, saved_name: str, *, songdata_db: Optional[Path], beatoraja_base: Optional[Path]):
        super().__init__()
        self.parser = parser
        self.table_source = table_source
        self.saved_name = saved_name
        self.songdata_db = songdata_db
        self.beatoraja_base = beatoraja_base

    def run(self) -> None:  # type: ignore[override]
        try:
            response = requests.get(self.table_source, timeout=15)
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "").lower()
            if "html" in content_type or self.table_source.lower().endswith((".html", ".htm")):
                suffix = ".html"
            elif self.table_source.lower().endswith(".json"):
                suffix = ".json"
            elif self.table_source.lower().endswith(".csv"):
                suffix = ".csv"
            else:
                suffix = ".html" if "<html" in response.text.lower() else ".csv"
            table = load_difficulty_table_from_content(
                self.saved_name,
                response.text,
                suffix,
                source_url=self.table_source,
            )
            analyses = analyze_table(
                table,
                self.parser,
                songdata_db=self.songdata_db,
                beatoraja_base=self.beatoraja_base,
            )
            self.finished.emit(table, analyses)
        except Exception:  # noqa: BLE001
            self.failed.emit(traceback.format_exc())


class SingleAnalysisTab(QWidget):
    def __init__(self, parser: PMSParser, parent=None) -> None:
        super().__init__(parent)
        self.parser = parser
        self.setAcceptDrops(True)
        self.chart = StackedDensityChart(self)
        self.metrics_labels: Dict[str, QLabel] = {}
        self.status_label = QLabel(".pms ファイルをドラッグ＆ドロップしてください")
        self.file_label = QLabel("未選択")
        self.analyze_button = QPushButton("ファイルを開く")
        self._worker: Optional[AnalysisWorker] = None
        self._current_path: Optional[Path] = None
        self._build_ui()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout()
        main_layout.addWidget(self.chart)

        info_layout = QHBoxLayout()
        info_layout.addWidget(QLabel("選択ファイル:"))
        info_layout.addWidget(self.file_label, 1)
        info_layout.addWidget(self.analyze_button)
        main_layout.addLayout(info_layout)

        metrics_group = QGroupBox("密度メトリクス")
        grid = QGridLayout()
        labels = {
            "max_density": "秒間密度(最大)",
            "terminal_density": "終端秒間密度(終盤5秒平均)",
            "average_density": "平均密度(全体)",
            "rms_density": "RMS",
        }
        for row, (key, title) in enumerate(labels.items()):
            if key == "rms_density":
                title_label = QLabel(title)
                info = QLabel("？")
                info.setToolTip("秒間密度の二乗平均平方根。ゲージの増加量を加味しており、休憩地帯や局所難の影響を受けにくい。")
                info.setFixedWidth(16)
                info.setAlignment(Qt.AlignmentFlag.AlignCenter)
                info.setStyleSheet(
                    "QLabel { border: 1px solid #888; border-radius: 8px; background: #eee; color: #333; }"
                )
                info_layout = QHBoxLayout()
                info_layout.addWidget(title_label)
                info_layout.addWidget(info)
                info_layout.addStretch()
                container = QWidget()
                container.setLayout(info_layout)
                grid.addWidget(container, row, 0)
            else:
                grid.addWidget(QLabel(title), row, 0)
            value_label = QLabel("-")
            self.metrics_labels[key] = value_label
            grid.addWidget(value_label, row, 1)
        metrics_group.setLayout(grid)
        main_layout.addWidget(metrics_group)

        main_layout.addWidget(self.status_label)
        main_layout.addItem(QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))
        self.setLayout(main_layout)

        self.analyze_button.clicked.connect(self._open_file_dialog)

    def _open_file_dialog(self) -> None:
        file_name, _ = QFileDialog.getOpenFileName(self, "PMS ファイルを開く", "", "PMS Files (*.pms *.bms)")
        if file_name:
            self.load_file(Path(file_name))

    def load_file(self, path: Path) -> None:
        self._current_path = path
        self.file_label.setText(str(path))
        self.status_label.setText("解析中...")
        self._worker = AnalysisWorker(self.parser, path)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_finished(self, parse_result, density: DensityResult) -> None:
        title_text = parse_result.title
        if parse_result.subtitle:
            title_text = f"{parse_result.title} {parse_result.subtitle}"
        self.chart.plot(density.per_second_by_key, title=title_text)
        self._update_metrics(density)
        self.status_label.setText(f"解析完了: {title_text}")
        record = AnalysisRecord(
            file_path=str(parse_result.file_path),
            title=title_text,
            artist=parse_result.artist,
            difficulty=None,
            metrics={
                "max_density": density.max_density,
                "average_density": density.average_density,
                "terminal_density": density.terminal_density,
                "rms_density": density.rms_density,
            },
        )
        append_history(record)

    def _on_failed(self, error_message: str) -> None:
        self.status_label.setText("解析に失敗しました")
        QMessageBox.critical(self, "エラー", error_message)

    def _update_metrics(self, density: DensityResult) -> None:
        self.metrics_labels["max_density"].setText(f"{density.max_density:.2f} note/s")
        self.metrics_labels["terminal_density"].setText(f"{density.terminal_density:.2f} note/s")
        self.metrics_labels["average_density"].setText(f"{density.average_density:.2f} note/s")
        self.metrics_labels["rms_density"].setText(f"{density.rms_density:.2f} note/s")

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # type: ignore[override]
        urls = event.mimeData().urls()
        if urls:
            path = Path(urls[0].toLocalFile())
            if path.suffix.lower() in {".pms", ".bms"}:
                self.load_file(path)
            else:
                QMessageBox.warning(self, "不正な形式", ".pms または .bms ファイルを指定してください")


class DifficultyTab(QWidget):
    def __init__(self, parser: PMSParser, parent=None) -> None:
        super().__init__(parent)
        self.parser = parser
        self.loading_label = QLabel("")
        self.difficulty_chart = DifficultyScatterChart(self)
        self.box_chart = BoxPlotCanvas(self)
        self.box_chart.hide()
        self.table_widget = QTableWidget(0, 11)
        self.table_widget.setHorizontalHeaderLabels(
            [
                "LEVEL",
                "曲名",
                "総NOTES数",
                "TOTAL値",
                "増加率",
                "平均密度",
                "終端密度",
                "RMS",
                "md5",
                "sha256",
                "Path",
            ]
        )
        self.table_widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.load_button = QPushButton("読み込む")
        self.analyze_button = QPushButton("更新")
        self.delete_button = QPushButton("削除")
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://example.com/table.json など")
        self.url_list = QComboBox()
        self.url_list.setEditable(False)
        self.metric_selector = QComboBox()
        self.metric_selector.addItems(["総NOTES", "平均密度", "終端密度", "RMS"])
        self.chart_type_selector = QComboBox()
        self.chart_type_selector.addItems(["散布図", "箱ひげ図"])
        self.summary_table = QTableWidget(0, 9)
        self.summary_table.setHorizontalHeaderLabels(
            ["LEVEL", "総NOTES数", "増加率", "最小", "Q1", "中央値", "Q3", "最大", "平均"]
        )
        self.summary_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.songdata_label = QLabel("songdata.db: 未設定")
        self._latest_analyses: List[ChartAnalysis] = []
        self._cached_results: Dict[str, List[ChartAnalysis]] = {}
        self._cached_symbols: Dict[str, str] = {}
        self._current_symbol: str = ""
        self._cached_results: Dict[str, List[ChartAnalysis]] = {}
        self._current_symbol: str = ""
        self._current_url: Optional[str] = None
        self._worker: Optional[DifficultyTableWorker] = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout()
        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("URL:"))
        header_layout.addWidget(self.url_input, 2)
        header_layout.addWidget(self.load_button)
        layout.addLayout(header_layout)

        saved_layout = QHBoxLayout()
        saved_layout.addWidget(QLabel("保存済み:"))
        saved_layout.addWidget(self.url_list, 1)
        saved_layout.addWidget(self.analyze_button)
        saved_layout.addWidget(self.delete_button)
        layout.addLayout(saved_layout)

        layout.addWidget(self.loading_label)
        layout.addWidget(self.songdata_label)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)

        table_container = QWidget()
        table_layout = QVBoxLayout()
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.addWidget(self.table_widget)
        table_container.setLayout(table_layout)

        chart_container = QWidget()
        chart_layout = QVBoxLayout()
        chart_layout.setContentsMargins(0, 0, 0, 0)
        metric_layout = QHBoxLayout()
        metric_layout.addStretch()
        metric_layout.addWidget(QLabel("縦軸:"))
        metric_layout.addWidget(self.metric_selector)
        metric_layout.addWidget(QLabel("グラフ:"))
        metric_layout.addWidget(self.chart_type_selector)
        chart_layout.addLayout(metric_layout)
        chart_layout.addWidget(self.difficulty_chart)
        chart_layout.addWidget(self.box_chart)
        chart_layout.addWidget(self.summary_table)
        chart_container.setLayout(chart_layout)

        splitter.addWidget(table_container)
        splitter.addWidget(chart_container)
        layout.addWidget(splitter)
        self.setLayout(layout)

        self.load_button.clicked.connect(self._select_table)
        self.analyze_button.clicked.connect(self._analyze_table)
        self.url_list.currentTextChanged.connect(self._on_select_saved)
        self.metric_selector.currentTextChanged.connect(self._refresh_chart_only)
        self.chart_type_selector.currentTextChanged.connect(self._refresh_chart_only)
        self.delete_button.clicked.connect(self._delete_saved)
        self._refresh_saved_urls()
        self.refresh_songdata_label()

    def _select_table(self) -> None:
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "未入力", "URL を入力してください")
            return
        self._start_download(url)

    def _analyze_table(self) -> None:
        # 再解析: 入力欄が空なら選択中を使う
        url = self.url_input.text().strip() or self.url_list.currentText() or self._current_url
        if not url:
            QMessageBox.warning(self, "未選択", "難易度表の URL を入力するか保存済みから選択してください")
            return
        if url in self._cached_results:
            self._start_download(url, add_to_saved=False, force_refresh=True)
            return
        self._start_download(url, add_to_saved=False, force_refresh=True)

    def _on_finished(self, table: DifficultyTable, analyses: List) -> None:
        self.analyze_button.setEnabled(True)
        self.load_button.setEnabled(True)
        self._latest_analyses = analyses
        self._cached_results[self._current_url or ""] = analyses
        if self._current_url:
            self._cached_symbols[self._current_url] = table.symbol or ""
        self._current_symbol = table.symbol or ""
        self._render_table_and_chart()
        self.loading_label.setText("")

    def _on_failed(self, error_message: str) -> None:
        self.analyze_button.setEnabled(True)
        self.load_button.setEnabled(True)
        self.loading_label.setText("")
        QMessageBox.critical(self, "エラー", error_message)

    def _start_download(self, url: str, *, add_to_saved: bool = True, force_refresh: bool = False) -> None:
        name = Path(url).stem or "table"
        self.analyze_button.setEnabled(False)
        self.load_button.setEnabled(False)
        self.loading_label.setText("読み込み/解析中です。数分かかる場合があります...")
        self._current_url = url
        config = load_config()
        songdata_dir = Path(config["songdata_dir"]) if config.get("songdata_dir") else None
        songdata_db = songdata_dir / "songdata.db" if songdata_dir else None
        if songdata_db and not songdata_db.exists():
            QMessageBox.critical(self, "songdata.db なし", f"songdata.db が見つかりませんでした: {songdata_db}")
            self.analyze_button.setEnabled(True)
            self.load_button.setEnabled(True)
            return
        if songdata_db:
            try:
                import sqlite3

                con = sqlite3.connect(str(songdata_db))
                con.close()
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "songdata.db 読み込み失敗", f"songdata.db を開けませんでした: {exc}")
                self.analyze_button.setEnabled(True)
                self.load_button.setEnabled(True)
                return
        self._worker = DifficultyTableWorker(
            self.parser, url, name, songdata_db=songdata_db, beatoraja_base=songdata_dir
        )
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()
        if add_to_saved:
            add_saved_table(url)
            self._refresh_saved_urls()
        self.refresh_songdata_label()

    def _refresh_saved_urls(self) -> None:
        self.url_list.clear()
        urls = get_saved_tables()
        self.url_list.addItems(urls)
        if urls:
            self.url_list.setCurrentIndex(0)
            cached = self._cached_results.get(urls[0])
            if cached:
                self._latest_analyses = cached
                self._current_symbol = self._cached_symbols.get(urls[0], "")
                self._render_table_and_chart()

    def _on_select_saved(self, value: str) -> None:
        if value:
            self.url_input.setText(value)
            if value in self._cached_results:
                self._latest_analyses = self._cached_results[value]
                self._current_symbol = self._cached_symbols.get(value, "")
                self._render_table_and_chart()

    def _delete_saved(self) -> None:
        current = self.url_list.currentText()
        if not current:
            return
        remove_saved_table(current)
        if current in self._cached_results:
            self._cached_results.pop(current, None)
            self._cached_symbols.pop(current, None)
        self._refresh_saved_urls()

    def refresh_songdata_label(self) -> None:
        config = load_config()
        songdata_dir = config.get("songdata_dir")
        if songdata_dir:
            self.songdata_label.setText(f"songdata.db: {songdata_dir}")
        else:
            self.songdata_label.setText("songdata.db: 未設定")

    def _refresh_chart_only(self) -> None:
        if not self._latest_analyses:
            return
        self._render_chart()

    def _render_table_and_chart(self) -> None:
        analyses = self._latest_analyses
        self.table_widget.setRowCount(len(analyses))
        for row, analysis in enumerate(analyses):
            entry = analysis.entry
            density = analysis.density
            difficulty_display = self._format_difficulty(analysis.difficulty)
            title_text = entry.title
            if entry.subtitle:
                title_text = f"{entry.title} {entry.subtitle}"
            rate = "-"
            if analysis.total_value is not None and analysis.note_count:
                rate = f"{analysis.total_value / analysis.note_count:.2f}"

            self.table_widget.setItem(row, 0, QTableWidgetItem(difficulty_display))
            self.table_widget.setItem(row, 1, QTableWidgetItem(title_text))
            self.table_widget.setItem(row, 2, QTableWidgetItem(str(analysis.note_count or 0)))
            self.table_widget.setItem(row, 3, QTableWidgetItem(f"{analysis.total_value:.2f}" if analysis.total_value is not None else "-"))
            self.table_widget.setItem(row, 4, QTableWidgetItem(rate))
            self.table_widget.setItem(row, 5, QTableWidgetItem(f"{density.average_density:.2f}"))
            self.table_widget.setItem(row, 6, QTableWidgetItem(f"{density.terminal_density:.2f}"))
            self.table_widget.setItem(row, 7, QTableWidgetItem(f"{density.rms_density:.2f}"))
            self.table_widget.setItem(row, 8, QTableWidgetItem(analysis.md5 or ""))
            self.table_widget.setItem(row, 9, QTableWidgetItem(analysis.sha256 or ""))
            self.table_widget.setItem(row, 10, QTableWidgetItem(str(analysis.resolved_path) if analysis.resolved_path else ""))

        self._render_chart()
        self._render_summary()

    def _format_difficulty(self, value: str) -> str:
        symbol = self._current_symbol or ""
        if symbol and not value.startswith(symbol):
            return f"{symbol}{value}"
        return value

    def _render_chart(self) -> None:
        metric = self.metric_selector.currentText()
        data: Dict[str, List[float]] = {}
        for analysis in self._latest_analyses:
            density = analysis.density
            if metric == "総NOTES":
                value = float(analysis.note_count or 0)
            elif metric == "終端密度":
                value = density.terminal_density
            elif metric == "RMS":
                value = density.rms_density
            else:
                value = density.average_density
            key = self._format_difficulty(analysis.difficulty)
            data.setdefault(key, []).append(value)

        ordered_keys = sorted(data.keys(), key=self._difficulty_sort_key)
        scatter_points = []
        for key in ordered_keys:
            for v in data[key]:
                scatter_points.append((key, v))

        # Toggle charts
        if self.chart_type_selector.currentText() == "箱ひげ図":
            self.difficulty_chart.hide()
            self.box_chart.show()
            self.box_chart.plot({k: data[k] for k in ordered_keys}, metric)
        else:
            self.box_chart.hide()
            self.difficulty_chart.show()
            self.difficulty_chart.plot(scatter_points, y_label=metric)

    def _difficulty_sort_key(self, value: str) -> float:
        import re

        # remove non-digit and dot to sort numerically; fallback to 0
        digits = re.findall(r"[0-9]+(?:\\.[0-9]+)?", value)
        try:
            return float(digits[0]) if digits else float("inf")
        except ValueError:
            return float("inf")

    def _render_summary(self) -> None:
        metric = self.metric_selector.currentText()
        rows = {}
        for analysis in self._latest_analyses:
            key = self._format_difficulty(analysis.difficulty)
            density = analysis.density
            if metric == "総NOTES":
                val = float(analysis.note_count or 0)
            elif metric == "終端密度":
                val = density.terminal_density
            elif metric == "RMS":
                val = density.rms_density
            else:
                val = density.average_density
            rows.setdefault(key, {"values": [], "notes": [], "rates": []})
            rows[key]["values"].append(val)
            if analysis.note_count is not None:
                rows[key]["notes"].append(analysis.note_count)
            if analysis.total_value is not None and analysis.note_count:
                rows[key]["rates"].append(analysis.total_value / analysis.note_count)

        ordered = sorted(rows.keys(), key=self._difficulty_sort_key)
        if not ordered:
            self.summary_table.setRowCount(0)
            return
        self.summary_table.setRowCount(len(ordered))
        for idx, key in enumerate(ordered):
            values = rows[key]["values"]
            notes_list = rows[key]["notes"]
            rates_list = rows[key]["rates"]
            self.summary_table.setItem(idx, 0, QTableWidgetItem(key))
            self.summary_table.setItem(idx, 1, QTableWidgetItem(f"{_mean(notes_list):.2f}" if notes_list else "-"))
            self.summary_table.setItem(idx, 2, QTableWidgetItem(f"{_mean(rates_list):.4f}" if rates_list else "-"))
            stats = _quantiles(values)
            labels = [stats["min"], stats["q1"], stats["median"], stats["q3"], stats["max"], stats["mean"]]
            for col, val in enumerate(labels, start=3):
                text = "-" if val is None else f"{val:.2f}"
                self.summary_table.setItem(idx, col, QTableWidgetItem(text))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PMS Chart Analyzer")
        self.resize(1100, 720)
        self.setAcceptDrops(True)
        self.parser = PMSParser()
        self.tabs = QTabWidget()
        self.tabs.setAcceptDrops(True)
        self.tabs.installEventFilter(self)
        self.tabs.setTabPosition(QTabWidget.TabPosition.West)
        self.single_tab = SingleAnalysisTab(self.parser, self)
        self.table_tab = DifficultyTab(self.parser, self)
        self.tabs.addTab(self.single_tab, "単曲分析")
        self.tabs.addTab(self.table_tab, "難易度表")
        self.setCentralWidget(self.tabs)
        self._load_config()
        self._build_menu()

    def _build_menu(self) -> None:
        menu = self.menuBar()
        file_menu = menu.addMenu("ファイル")
        open_action = QAction("PMS ファイルを開く", self)
        open_action.triggered.connect(self.single_tab._open_file_dialog)
        file_menu.addAction(open_action)

        settings_menu = menu.addMenu("設定")
        set_path_action = QAction("songdata.db パスを指定", self)
        set_path_action.triggered.connect(self._select_songdata_path)
        settings_menu.addAction(set_path_action)

    def _select_songdata_path(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "songdata.db があるフォルダーを選択")
        if directory:
            config = load_config()
            config["songdata_dir"] = directory
            save_config(config)
            self.table_tab.refresh_songdata_label()
            QMessageBox.information(self, "保存", "songdata.db のパスを保存しました")

    def _load_config(self) -> None:
        config = load_config()
        if config.get("songdata_dir"):
            self.statusBar().showMessage(f"songdata.db: {config['songdata_dir']}")
            self.table_tab.refresh_songdata_label()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # type: ignore[override]
        self._handle_drop(event.mimeData().urls())

    def eventFilter(self, source, event):  # type: ignore[override]
        if source is self.tabs and event.type() in (
            QEvent.Type.DragEnter,
            QEvent.Type.DragMove,
            QEvent.Type.Drop,
        ):
            if event.mimeData().hasUrls():
                event.acceptProposedAction()
                if event.type() == QEvent.Type.Drop:
                    self._handle_drop(event.mimeData().urls())
            return True
        return super().eventFilter(source, event)

    def _handle_drop(self, urls) -> None:
        if urls:
            path = Path(urls[0].toLocalFile())
            if path.suffix.lower() in {".pms", ".bms"}:
                self.single_tab.load_file(path)
            else:
                QMessageBox.warning(self, "不正な形式", ".pms または .bms ファイルを指定してください")

    def _refresh_songdata_label(self) -> None:
        # Backward compatibility: call the public method used by MainWindow
        self.refresh_songdata_label()


def run_app() -> None:
    import sys

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


__all__ = ["MainWindow", "run_app"]
