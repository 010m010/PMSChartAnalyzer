from __future__ import annotations

import traceback
from pathlib import Path
from typing import Dict, List, Optional
from statistics import mean

from PyQt6.QtCore import QEvent, QThread, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QDragEnterEvent, QDropEvent, QDragMoveEvent, QColor
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
    QLineEdit,
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
    QDialog,
    QDialogButtonBox,
    QCheckBox,
    QScrollArea,
    QRadioButton,
    QButtonGroup,
    QMenu,
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
from ..theme import apply_app_palette
from ..utils import difficulty_sort_key
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
            density = compute_density(result.notes, result.total_time, total_value=result.total_value)
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
        self.scale_input = QLineEdit()
        self.scale_input.setPlaceholderText("縦軸の最大値を入力")
        self.scale_button = QPushButton("更新")
        self._manual_y_max_single: float | None = None
        self._latest_single_parse = None
        self._latest_single_density = None
        self.info_labels: Dict[str, QLabel] = {}
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
        info_layout.addWidget(self.analyze_button)
        info_layout.addWidget(QLabel("選択ファイル:"))
        self.file_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.file_label.setMinimumWidth(200)
        info_layout.addWidget(self.file_label, 1)
        info_layout.addWidget(self.scale_input)
        info_layout.addWidget(self.scale_button)
        main_layout.addLayout(info_layout)

        info_group = QGroupBox("基本情報")
        info_grid = QGridLayout()
        info_fields = [
            ("title", "TITLE"),
            ("subtitle", "SUBTITLE"),
            ("genre", "GENRE"),
            ("artist", "ARTIST"),
            ("subartist", "SUBARTIST"),
            ("bpm", "BPM"),
            ("rank", "RANK"),
            ("level", "LEVEL"),
            ("total", "TOTAL"),
            ("notes", "NOTES数"),
            ("rate", "増加率 (/notes)"),
        ]
        for row, (key, label) in enumerate(info_fields):
            lbl = QLabel(label)
            lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            info_grid.addWidget(lbl, row, 0)
            value_label = QLabel("-")
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value_label.setFixedWidth(240)
            self.info_labels[key] = value_label
            info_grid.addWidget(value_label, row, 1)
        info_grid.setColumnMinimumWidth(0, 120)
        info_grid.setColumnMinimumWidth(1, 240)
        info_grid.setColumnStretch(0, 0)
        info_grid.setColumnStretch(1, 0)
        info_group.setLayout(info_grid)
        main_layout.addWidget(info_group)

        metrics_group = QGroupBox("密度メトリクス")
        grid = QGridLayout()
        labels = {
            "max_density": "秒間密度(最大)",
            "terminal_density": "終端密度(クリアゲージ基準)",
            "terminal_rms_density": "終端RMS(クリアゲージ基準)",
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
                lbl = QLabel(title)
                lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                grid.addWidget(lbl, row, 0)
            value_label = QLabel("-")
            value_label.setFixedWidth(180)
            self.metrics_labels[key] = value_label
            grid.addWidget(value_label, row, 1)
        grid.setColumnMinimumWidth(0, 170)
        grid.setColumnMinimumWidth(1, 180)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 0)
        metrics_group.setLayout(grid)
        main_layout.addWidget(metrics_group)

        main_layout.addWidget(self.status_label)
        main_layout.addItem(QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))
        self.setLayout(main_layout)

        self.analyze_button.clicked.connect(self._open_file_dialog)
        self.scale_button.clicked.connect(self._apply_single_scale)

    def set_theme_mode(self, mode: str) -> None:
        self.chart.set_theme_mode(mode)
        self.chart.draw()

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
        self._latest_single_parse = parse_result
        self._latest_single_density = density
        title_text = parse_result.title
        if parse_result.subtitle:
            title_text = f"{parse_result.title} {parse_result.subtitle}"
        self.chart.plot(
            density.per_second_by_key,
            title=title_text,
            total_time=density.duration,
            terminal_window=density.terminal_window,
            y_max=self._manual_y_max_single,
        )
        self._update_info(parse_result)
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
                "terminal_rms_density": density.terminal_rms_density,
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
        self.metrics_labels["terminal_rms_density"].setText(f"{density.terminal_rms_density:.2f} note/s")
        self.metrics_labels["average_density"].setText(f"{density.average_density:.2f} note/s")
        self.metrics_labels["rms_density"].setText(f"{density.rms_density:.2f} note/s")

    def _apply_single_scale(self) -> None:
        text = self.scale_input.text().strip()
        if not text:
            self._manual_y_max_single = None
            return
        try:
            value = float(text)
            if value <= 0:
                raise ValueError
            self._manual_y_max_single = value
        except ValueError:
            QMessageBox.warning(self, "不正な値", "0 より大きい数値を入力してください")
            return
        if self._latest_single_density and self._latest_single_parse:
            parse_result = self._latest_single_parse
            density = self._latest_single_density
            self.chart.plot(
                density.per_second_by_key,
                title=parse_result.title,
                total_time=density.duration,
                terminal_window=density.terminal_window,
                y_max=self._manual_y_max_single,
            )

    def _update_info(self, parse_result) -> None:
        def _set_text(key: str, text: str, *, color: str | None = None) -> None:
            label = self.info_labels.get(key)
            if not label:
                return
            label.setText(text)
            if color:
                label.setStyleSheet(f"color: {color};")
            else:
                label.setStyleSheet("")

        _set_text("title", parse_result.title or "-")
        _set_text("subtitle", parse_result.subtitle or "-")
        _set_text("genre", parse_result.genre or "-")
        _set_text("artist", parse_result.artist or "-")
        _set_text("subartist", parse_result.subartist or "-")

        if parse_result.min_bpm != parse_result.max_bpm:
            bpm_text = f"{parse_result.start_bpm:.2f} ({parse_result.min_bpm:.2f}～{parse_result.max_bpm:.2f})"
        else:
            bpm_text = f"{parse_result.start_bpm:.2f}"
        _set_text("bpm", bpm_text)

        rank_labels = {
            0: "Very Hard",
            1: "Hard",
            2: "Normal",
            3: "Easy",
            4: "Very Easy",
        }
        if parse_result.rank is not None and parse_result.rank in rank_labels:
            rank_text = f"{parse_result.rank} ({rank_labels[parse_result.rank]})"
        else:
            rank_text = "未定義"
        _set_text("rank", rank_text)

        _set_text("level", parse_result.level or "-")

        if parse_result.total_value is None:
            _set_text("total", "未定義", color="red")
            rate_text = "未定義"
        else:
            _set_text("total", f"{parse_result.total_value:.2f}")
            note_count = len(parse_result.notes)
            rate_text = f"{(parse_result.total_value / note_count):.4f}" if note_count else "未定義"

        _set_text("notes", str(len(parse_result.notes)))
        _set_text("rate", rate_text)

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
        self.table_widget = QTableWidget(0, 13)
        self.table_widget.setHorizontalHeaderLabels(
            [
                "LEVEL",
                "曲名",
                "総NOTES数",
                "TOTAL値",
                "増加率",
                "最大瞬間密度",
                "平均密度",
                "RMS",
                "終端密度",
                "終端RMS",
                "md5",
                "sha256",
                "Path",
            ]
        )
        self.table_widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_widget.setSortingEnabled(True)
        self.table_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.load_button = QPushButton("読み込む")
        self.analyze_button = QPushButton("更新")
        self.delete_button = QPushButton("削除")
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://example.com/table.json など")
        self.url_list = QComboBox()
        self.url_list.setEditable(False)
        self.metric_selector = QComboBox()
        self.metric_selector.addItems(["総NOTES", "最大瞬間密度", "平均密度", "RMS", "終端密度", "終端RMS"])
        self.chart_type_selector = QComboBox()
        self.chart_type_selector.addItems(["散布図", "箱ひげ図"])
        self.chart_type_selector.setCurrentIndex(1)
        self.scale_input = QLineEdit()
        self.scale_input.setPlaceholderText("縦軸の最大値を入力")
        self.scale_button = QPushButton("更新")
        self._manual_y_max: float | None = None
        self.summary_metric_selector = QComboBox()
        self.summary_metric_selector.addItems(
            ["総NOTES", "増加率", "最大瞬間密度", "平均密度", "RMS", "終端密度", "終端RMS"]
        )
        self.filter_button = QPushButton("絞り込み")
        self._filter_selection: set[str] = set()
        self.summary_table = QTableWidget(0, 8)
        self.summary_table.setHorizontalHeaderLabels(
            ["LEVEL", "解析済み譜面数", "平均", "最小", "Q1", "中央値", "Q3", "最大"]
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
        self._open_single_callback: Optional[callable[[Path], None]] = None
        self._build_ui()
        self._available_levels: list[str] = []

    def set_open_single_handler(self, handler: callable[[Path], None]) -> None:
        self._open_single_callback = handler

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

        filter_layout = QHBoxLayout()
        filter_layout.addWidget(self.filter_button)
        filter_layout.addStretch()

        chart_container = QWidget()
        chart_layout = QVBoxLayout()
        chart_layout.setContentsMargins(0, 0, 0, 0)
        metric_layout = QHBoxLayout()
        metric_layout.addStretch()
        metric_layout.addWidget(QLabel("縦軸:"))
        metric_layout.addWidget(self.metric_selector)
        metric_layout.addWidget(QLabel("グラフ:"))
        metric_layout.addWidget(self.chart_type_selector)
        metric_layout.addWidget(QLabel("スケール調整:"))
        metric_layout.addWidget(self.scale_input)
        metric_layout.addWidget(self.scale_button)

        chart_area = QWidget()
        chart_area_layout = QVBoxLayout()
        chart_area_layout.setContentsMargins(0, 0, 0, 0)
        chart_area_layout.addLayout(metric_layout)
        chart_area_layout.addWidget(self.difficulty_chart)
        chart_area_layout.addWidget(self.box_chart)
        chart_area.setLayout(chart_area_layout)

        summary_container = QWidget()
        summary_layout = QVBoxLayout()
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_header = QHBoxLayout()
        summary_header.addWidget(QLabel("難易度ごとの統計"))
        summary_header.addStretch()
        summary_header.addWidget(QLabel("項目:"))
        summary_header.addWidget(self.summary_metric_selector)
        summary_layout.addLayout(summary_header)
        summary_layout.addWidget(self.summary_table)
        summary_container.setLayout(summary_layout)

        chart_splitter = QSplitter(Qt.Orientation.Vertical)
        chart_splitter.setChildrenCollapsible(False)
        chart_splitter.addWidget(chart_area)
        chart_splitter.addWidget(summary_container)

        chart_layout.addWidget(chart_splitter)
        chart_container.setLayout(chart_layout)

        splitter.addWidget(table_container)
        splitter.addWidget(chart_container)
        layout.addLayout(filter_layout)
        layout.addWidget(splitter)
        self.setLayout(layout)

        self.load_button.clicked.connect(self._select_table)
        self.analyze_button.clicked.connect(self._analyze_table)
        self.url_list.currentTextChanged.connect(self._on_select_saved)
        self.metric_selector.currentTextChanged.connect(self._refresh_chart_only)
        self.chart_type_selector.currentTextChanged.connect(lambda: self._refresh_chart_only(clear_scale=True))
        self.summary_metric_selector.currentTextChanged.connect(self._render_summary)
        self.scale_button.clicked.connect(self._apply_manual_scale)
        self.delete_button.clicked.connect(self._delete_saved)
        self.filter_button.clicked.connect(self._open_filter_dialog)
        self.table_widget.customContextMenuRequested.connect(self._show_table_context_menu)
        self._refresh_saved_urls()
        self.refresh_songdata_label()

    def set_theme_mode(self, mode: str) -> None:
        self.difficulty_chart.set_theme_mode(mode)
        self.box_chart.set_theme_mode(mode)
        self._render_chart()

    def _select_table(self) -> None:
        url = self.url_input.text().strip()
        if not url:
            return
        self._start_download(url)

    def _analyze_table(self) -> None:
        url = self.url_list.currentText().strip()
        if not url:
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
                self._reset_sorting()
                self._sync_filter_options()
                self._apply_filter_defaults()

    def _on_select_saved(self, value: str) -> None:
        if value:
            if value in self._cached_results:
                self._latest_analyses = self._cached_results[value]
                self._current_symbol = self._cached_symbols.get(value, "")
                self._render_table_and_chart()
                self._reset_sorting()
                self._sync_filter_options()
                self._apply_filter_defaults()

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

    def _refresh_chart_only(self, *, clear_scale: bool = False) -> None:
        if clear_scale:
            self._manual_y_max = None
            self.scale_input.clear()
        if not self._latest_analyses:
            return
        self._render_chart()

    def _render_table_and_chart(self) -> None:
        analyses = self._latest_analyses
        visible = [a for a in analyses if self._is_difficulty_visible(a.difficulty)]
        sorting_state = self.table_widget.isSortingEnabled()
        if sorting_state:
            self.table_widget.setSortingEnabled(False)
            header = self.table_widget.horizontalHeader()
            current_sort = (header.sortIndicatorSection(), header.sortIndicatorOrder())
        else:
            current_sort = None
        self.table_widget.setRowCount(len(visible))
        for row, analysis in enumerate(visible):
            entry = analysis.entry
            density = analysis.density
            difficulty_display = self._format_difficulty(analysis.difficulty)
            level_key = difficulty_sort_key(difficulty_display)
            title_text = entry.title
            if entry.subtitle:
                title_text = f"{entry.title} {entry.subtitle}"
            rate = "-"
            if analysis.total_value is not None and analysis.note_count:
                rate = f"{analysis.total_value / analysis.note_count:.2f}"

            level_item = QTableWidgetItem(difficulty_display)
            if isinstance(level_key[1], (int, float)):
                level_item.setData(Qt.ItemDataRole.UserRole, float(level_key[1]))
            self.table_widget.setItem(row, 0, level_item)
            title_item = QTableWidgetItem(title_text)
            if not analysis.resolved_path:
                title_item.setForeground(QColor("red"))
                title_item.setText(f"{title_text}（未解析）")
            self.table_widget.setItem(row, 1, title_item)
            notes_item = QTableWidgetItem(str(analysis.note_count or 0))
            notes_item.setData(Qt.ItemDataRole.UserRole, float(analysis.note_count or 0))
            self.table_widget.setItem(row, 2, notes_item)
            if analysis.total_value is None:
                total_item = QTableWidgetItem("未定義")
                total_item.setForeground(QColor("red"))
            else:
                total_item = QTableWidgetItem(f"{analysis.total_value:.2f}")
                total_item.setData(Qt.ItemDataRole.UserRole, float(analysis.total_value))
            self.table_widget.setItem(row, 3, total_item)
            rate_item = QTableWidgetItem(rate)
            if rate != "-":
                rate_item.setData(Qt.ItemDataRole.UserRole, float(rate))
            self.table_widget.setItem(row, 4, rate_item)
            max_item = QTableWidgetItem(f"{density.max_density:.2f}")
            max_item.setData(Qt.ItemDataRole.UserRole, float(density.max_density))
            self.table_widget.setItem(row, 5, max_item)
            avg_item = QTableWidgetItem(f"{density.average_density:.2f}")
            avg_item.setData(Qt.ItemDataRole.UserRole, float(density.average_density))
            self.table_widget.setItem(row, 6, avg_item)
            rms_item = QTableWidgetItem(f"{density.rms_density:.2f}")
            rms_item.setData(Qt.ItemDataRole.UserRole, float(density.rms_density))
            self.table_widget.setItem(row, 7, rms_item)
            term_item = QTableWidgetItem(f"{density.terminal_density:.2f}")
            term_item.setData(Qt.ItemDataRole.UserRole, float(density.terminal_density))
            self.table_widget.setItem(row, 8, term_item)
            term_rms_item = QTableWidgetItem(f"{density.terminal_rms_density:.2f}")
            term_rms_item.setData(Qt.ItemDataRole.UserRole, float(density.terminal_rms_density))
            self.table_widget.setItem(row, 9, term_rms_item)
            self.table_widget.setItem(row, 10, QTableWidgetItem(analysis.md5 or ""))
            self.table_widget.setItem(row, 11, QTableWidgetItem(analysis.sha256 or ""))
            self.table_widget.setItem(row, 12, QTableWidgetItem(str(analysis.resolved_path) if analysis.resolved_path else ""))

        self.table_widget.setSortingEnabled(sorting_state)
        if sorting_state and current_sort:
            self.table_widget.sortItems(*current_sort)
        else:
            # Default sort by LEVEL using numeric key
            self.table_widget.sortItems(0, Qt.SortOrder.AscendingOrder)
        self._render_chart()
        self._render_summary()
        self._sync_filter_options()
        self._apply_filter_defaults()

    def _format_difficulty(self, value: str) -> str:
        symbol = self._current_symbol or ""
        if symbol and not value.startswith(symbol):
            return f"{symbol}{value}"
        return value

    def _render_chart(self) -> None:
        metric = self.metric_selector.currentText()
        data: Dict[str, List[float]] = {}
        for analysis in self._latest_analyses:
            if not self._is_difficulty_visible(analysis.difficulty):
                continue
            if not analysis.resolved_path or not analysis.density.per_second_total:
                continue
            value = self._metric_value(analysis, metric)
            if value is None:
                continue
            key = self._format_difficulty(analysis.difficulty)
            data.setdefault(key, []).append(value)

        ordered_keys = sorted(data.keys(), key=difficulty_sort_key)
        scatter_points = []
        for key in ordered_keys:
            for v in data[key]:
                scatter_points.append((key, v))
        y_limits = (0, self._manual_y_max) if self._manual_y_max else None

        # Toggle charts
        if self.chart_type_selector.currentText() == "箱ひげ図":
            self.difficulty_chart.hide()
            self.box_chart.show()
            box_data = {k: data[k] for k in ordered_keys}
            self.box_chart.plot(box_data, metric, y_limits=y_limits)
        else:
            self.box_chart.hide()
            self.difficulty_chart.show()
            self.difficulty_chart.plot(
                scatter_points, y_label=metric, order=ordered_keys, sort_key=difficulty_sort_key, y_limits=y_limits
            )

    def _metric_value(self, analysis: ChartAnalysis, metric: str) -> float | None:
        density = analysis.density
        if metric == "総NOTES":
            return float(analysis.note_count or 0)
        if metric == "最大瞬間密度":
            return density.max_density
        if metric == "平均密度":
            return density.average_density
        if metric == "RMS":
            return density.rms_density
        if metric == "終端密度":
            return density.terminal_density
        if metric == "終端RMS":
            return density.terminal_rms_density
        if metric == "増加率":
            if analysis.total_value is not None and analysis.note_count:
                return analysis.total_value / analysis.note_count
            return None
        return None

    def _compute_y_limits(self, values: List[float]) -> Optional[tuple[float, float]]:
        if not values:
            return None
        sorted_vals = sorted(values)
        if len(sorted_vals) == 1:
            val = sorted_vals[0]
            return (val * 0.9, val * 1.1 if val != 0 else 1.0)

        def _percentile(p: float) -> float:
            k = (len(sorted_vals) - 1) * p
            f = int(k)
            c = min(f + 1, len(sorted_vals) - 1)
            return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)

        low = _percentile(0.05)
        high = _percentile(0.95)
        global_min = sorted_vals[0]
        global_max = sorted_vals[-1]
        if low == high:
            low *= 0.9
            high *= 1.1 if high != 0 else 1.0
        # Ensure the absolute min/max stay visible with a small margin
        low = min(low, global_min)
        high = max(high, global_max)
        padding = (high - low) * 0.05 if high != low else 1.0
        return (low - padding, high + padding)

    def _render_summary(self) -> None:
        metric = self.summary_metric_selector.currentText()
        rows = {}
        for analysis in self._latest_analyses:
            if not self._is_difficulty_visible(analysis.difficulty):
                continue
            key = self._format_difficulty(analysis.difficulty)
            rows.setdefault(key, {"values": [], "total": 0, "parsed": 0})
            rows[key]["total"] += 1  # total charts listed in the difficulty table
            if not analysis.resolved_path or not analysis.density.per_second_total:
                continue
            val = self._metric_value(analysis, metric)
            if val is None:
                continue
            rows[key]["parsed"] += 1
            rows[key]["values"].append(val)

        ordered = sorted(rows.keys(), key=difficulty_sort_key)
        if not ordered:
            self.summary_table.setRowCount(0)
            return
        self.summary_table.setRowCount(len(ordered))
        for idx, key in enumerate(ordered):
            values = rows[key]["values"]
            self.summary_table.setItem(idx, 0, QTableWidgetItem(key))
            count_text = f"{rows[key]['parsed']}/{rows[key]['total']}"
            count_item = QTableWidgetItem(count_text)
            if rows[key]["parsed"] < rows[key]["total"]:
                count_item.setForeground(QColor("red"))
            self.summary_table.setItem(idx, 1, count_item)
            stats = _quantiles(values)
            labels = [stats["mean"], stats["min"], stats["q1"], stats["median"], stats["q3"], stats["max"]]
            for col, val in enumerate(labels, start=2):
                text = "-" if val is None else f"{val:.2f}"
                self.summary_table.setItem(idx, col, QTableWidgetItem(text))

    def _apply_manual_scale(self) -> None:
        text = self.scale_input.text().strip()
        if not text:
            self._manual_y_max = None
            self._refresh_chart_only()
            return
        try:
            value = float(text)
            if value <= 0:
                raise ValueError
            self._manual_y_max = value
        except ValueError:
            QMessageBox.warning(self, "不正な値", "0 より大きい数値を入力してください")
            return
        self._refresh_chart_only()

    def _sync_filter_options(self) -> None:
        difficulties = {self._format_difficulty(a.difficulty) for a in self._latest_analyses}
        # Preserve existing checkbox states
        for level in list(self._level_filters.keys()):
            if level not in difficulties:
                self._level_filters.pop(level)
        for level in sorted(difficulties, key=difficulty_sort_key):
            if level not in self._level_filters:
                cb = QCheckBox(level)
                cb.setChecked(True)
                self._level_filters[level] = cb
        # Remove filters that were deselected but no longer exist
        self._filter_selection = {level for level, cb in self._level_filters.items() if cb.isChecked()}

    def _open_filter_dialog(self) -> None:
        self._sync_filter_options()
        dialog = QDialog(self)
        dialog.setWindowTitle("LEVEL を絞り込み")
        layout = QVBoxLayout(dialog)

        toggle_layout = QHBoxLayout()
        select_all_btn = QPushButton("すべて選択")
        clear_all_btn = QPushButton("すべて解除")
        toggle_layout.addWidget(select_all_btn)
        toggle_layout.addWidget(clear_all_btn)
        toggle_layout.addStretch()
        layout.addLayout(toggle_layout)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        container_layout = QVBoxLayout()
        checkboxes: list[QCheckBox] = []
        current_selection = self._filter_selection or set(self._available_levels)
        for level in self._available_levels:
            cb = QCheckBox(level)
            cb.setChecked(level in current_selection)
            container_layout.addWidget(cb)
            checkboxes.append(cb)
        container_layout.addStretch()
        container.setLayout(container_layout)
        scroll.setWidget(container)
        layout.addWidget(scroll)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(buttons)

        def select_all() -> None:
            for cb in checkboxes:
                cb.setChecked(True)

        def clear_all() -> None:
            for cb in checkboxes:
                cb.setChecked(False)

        select_all_btn.clicked.connect(select_all)
        clear_all_btn.clicked.connect(clear_all)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._filter_selection = {cb.text() for cb in checkboxes if cb.isChecked()}
            self._render_table_and_chart()

    def _show_table_context_menu(self, pos) -> None:
        item = self.table_widget.itemAt(pos)
        if item is None:
            return
        row = item.row()
        title_item = self.table_widget.item(row, 1)
        path_item = self.table_widget.item(row, 12)
        if path_item is None or not path_item.text():
            return
        path = Path(path_item.text())
        title = title_item.text() if title_item else str(path)

        menu = QMenu(self.table_widget)
        action = QAction(f"{title} の譜面情報を見る", self.table_widget)
        menu.addAction(action)

        def open_chart() -> None:
            if not self._open_single_callback:
                return
            if not path.exists():
                QMessageBox.warning(self, "ファイルなし", f"譜面ファイルが見つかりません: {path}")
                return
            self._open_single_callback(path)

        action.triggered.connect(open_chart)
        menu.exec(self.table_widget.viewport().mapToGlobal(pos))

    def _is_difficulty_visible(self, difficulty: str) -> bool:
        if not self._filter_selection:
            return True
        formatted = self._format_difficulty(difficulty)
        return formatted in self._filter_selection

    def _sync_filter_options(self) -> None:
        self._available_levels = sorted({self._format_difficulty(a.difficulty) for a in self._latest_analyses}, key=difficulty_sort_key)
        available_set = set(self._available_levels)
        if not self._filter_selection:
            self._filter_selection = available_set
        else:
            self._filter_selection = {level for level in self._filter_selection if level in available_set}
            if not self._filter_selection:
                self._filter_selection = available_set

    def _apply_filter_defaults(self) -> None:
        # Ensure all levels are visible after load/switch
        if self._available_levels:
            self._filter_selection = set(self._available_levels)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PMS Chart Analyzer")
        self.resize(1100, 720)
        self.setAcceptDrops(True)
        self.parser = PMSParser()
        self.theme_mode = "system"
        self.tabs = QTabWidget()
        self.tabs.setAcceptDrops(True)
        self.tabs.installEventFilter(self)
        self.tabs.setTabPosition(QTabWidget.TabPosition.West)
        self.single_tab = SingleAnalysisTab(self.parser, self)
        self.table_tab = DifficultyTab(self.parser, self)
        self.table_tab.set_open_single_handler(self._open_single_from_table)
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
        theme_menu = settings_menu.addMenu("テーマ")
        self.theme_action_group = QActionGroup(self)
        themes = [("システム設定に合わせる", "system"), ("ライトモード", "light"), ("ダークモード", "dark")]
        for label, value in themes:
            action = QAction(label, self, checkable=True)
            action.setData(value)
            if value == self.theme_mode:
                action.setChecked(True)
            self.theme_action_group.addAction(action)
            theme_menu.addAction(action)
        self.theme_action_group.triggered.connect(self._on_theme_selected)

    def _apply_theme_mode(self, mode: str, *, save: bool = True) -> None:
        self.theme_mode = mode
        app = QApplication.instance()
        if app:
            apply_app_palette(app, mode)
        self.single_tab.set_theme_mode(mode)
        self.table_tab.set_theme_mode(mode)
        if save:
            config = load_config()
            config["theme_mode"] = mode
            save_config(config)

    def _on_theme_selected(self, action: QAction) -> None:
        value = action.data()
        if isinstance(value, str):
            self._apply_theme_mode(value)

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
        if config.get("theme_mode"):
            self.theme_mode = config["theme_mode"]
        self._apply_theme_mode(self.theme_mode, save=False)
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
                self._open_single_from_table(path)
            else:
                QMessageBox.warning(self, "不正な形式", ".pms または .bms ファイルを指定してください")

    def _open_single_from_table(self, path: Path) -> None:
        self.tabs.setCurrentWidget(self.single_tab)
        self.single_tab.load_file(path)

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
