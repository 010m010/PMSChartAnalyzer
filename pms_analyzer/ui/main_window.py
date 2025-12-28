from __future__ import annotations

import traceback
from pathlib import Path
from typing import Dict, List, Optional

from PyQt6.QtCore import QThread, Qt, pyqtSignal
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
)
import requests

from ..analysis import DensityResult, compute_density
from ..difficulty_table import (
    DifficultyTable,
    analyze_table,
    load_difficulty_table_from_content,
)
from ..pms_parser import PMSParser
from ..storage import AnalysisRecord, add_saved_table, append_history, get_saved_tables, load_config, save_config
from .charts import BoxPlotCanvas, StackedDensityChart


class AnalysisWorker(QThread):
    finished = pyqtSignal(object, object)
    failed = pyqtSignal(str)

    def __init__(self, parser: PMSParser, path: Path, difficulty_label: str):
        super().__init__()
        self.parser = parser
        self.path = path
        self.difficulty_label = difficulty_label

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

    def __init__(self, parser: PMSParser, table_source: str, saved_name: str):
        super().__init__()
        self.parser = parser
        self.table_source = table_source
        self.saved_name = saved_name

    def run(self) -> None:  # type: ignore[override]
        try:
            response = requests.get(self.table_source, timeout=15)
            response.raise_for_status()
            suffix = ".json" if self.table_source.lower().endswith(".json") else ".csv"
            table = load_difficulty_table_from_content(self.saved_name, response.text, suffix)
            analyses = analyze_table(table, self.parser)
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
        self.difficulty_input = QLineEdit()
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
        info_layout.addWidget(QLabel("難易度ラベル:"))
        self.difficulty_input.setPlaceholderText("例: 10 または EX")
        info_layout.addWidget(self.difficulty_input)
        info_layout.addWidget(self.analyze_button)
        main_layout.addLayout(info_layout)

        metrics_group = QGroupBox("密度メトリクス")
        grid = QGridLayout()
        labels = {
            "max_density": "秒間密度(最大)",
            "terminal_density": "終端秒間密度(終盤5秒平均)",
            "average_density": "平均密度(全体)",
            "rms_density": "二乗平均密度",
        }
        for row, (key, title) in enumerate(labels.items()):
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
        difficulty = self.difficulty_input.text().strip()
        self._worker = AnalysisWorker(self.parser, path, difficulty)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_finished(self, parse_result, density: DensityResult) -> None:
        self.chart.plot(density.per_second_by_key)
        self._update_metrics(density)
        self.status_label.setText(f"解析完了: {parse_result.title}")
        record = AnalysisRecord(
            file_path=str(parse_result.file_path),
            title=parse_result.title,
            artist=parse_result.artist,
            difficulty=self.difficulty_input.text().strip() or None,
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
        self.table_label = QLabel("未読込")
        self.box_plot = BoxPlotCanvas(self)
        self.table_widget = QTableWidget(0, 4)
        self.table_widget.setHorizontalHeaderLabels(["難易度", "譜面数", "平均密度", "終端密度"])
        self.load_button = QPushButton("難易度表を読み込む")
        self.analyze_button = QPushButton("一括解析")
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://example.com/table.json など")
        self.url_list = QComboBox()
        self.url_list.setEditable(False)
        self._current_url: Optional[str] = None
        self._worker: Optional[DifficultyTableWorker] = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout()
        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("URL:"))
        header_layout.addWidget(self.url_input, 2)
        header_layout.addWidget(self.load_button)
        header_layout.addWidget(self.analyze_button)
        layout.addLayout(header_layout)

        saved_layout = QHBoxLayout()
        saved_layout.addWidget(QLabel("保存済み:"))
        saved_layout.addWidget(self.url_list, 1)
        saved_layout.addWidget(self.table_label)
        layout.addLayout(saved_layout)

        layout.addWidget(self.table_widget)
        layout.addWidget(self.box_plot)
        self.setLayout(layout)

        self.load_button.clicked.connect(self._select_table)
        self.analyze_button.clicked.connect(self._analyze_table)
        self.url_list.currentTextChanged.connect(self._on_select_saved)
        self._refresh_saved_urls()

    def _select_table(self) -> None:
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "未入力", "URL を入力してください")
            return
        self._start_download(url)

    def _analyze_table(self) -> None:
        url = self._current_url
        if not url:
            QMessageBox.warning(self, "未選択", "先に難易度表を読み込んでください")
            return
        self._start_download(url)

    def _on_finished(self, table: DifficultyTable, analyses: List) -> None:
        self.analyze_button.setEnabled(True)
        self.load_button.setEnabled(True)
        grouped: Dict[str, List[float]] = {}
        self.table_widget.setRowCount(len(analyses))
        for row, analysis in enumerate(analyses):
            densities = [d.max_density for d in analysis.results]
            avg_densities = [d.average_density for d in analysis.results]
            terminal_densities = [d.terminal_density for d in analysis.results]
            grouped[analysis.difficulty] = densities
            self.table_widget.setItem(row, 0, QTableWidgetItem(analysis.difficulty))
            self.table_widget.setItem(row, 1, QTableWidgetItem(str(len(analysis.results))))
            self.table_widget.setItem(row, 2, QTableWidgetItem(f"{sum(avg_densities)/len(avg_densities):.2f}"))
            self.table_widget.setItem(row, 3, QTableWidgetItem(f"{sum(terminal_densities)/len(terminal_densities):.2f}"))

        self.box_plot.plot(grouped, "秒間密度(最大)")
        self.table_label.setText(f"解析済み: {table.name}")

    def _on_failed(self, error_message: str) -> None:
        self.analyze_button.setEnabled(True)
        self.load_button.setEnabled(True)
        QMessageBox.critical(self, "エラー", error_message)

    def _start_download(self, url: str) -> None:
        name = Path(url).stem or "table"
        self.table_label.setText(url)
        self.analyze_button.setEnabled(False)
        self.load_button.setEnabled(False)
        self._current_url = url
        self._worker = DifficultyTableWorker(self.parser, url, name)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()
        add_saved_table(url)
        self._refresh_saved_urls()

    def _refresh_saved_urls(self) -> None:
        self.url_list.clear()
        urls = get_saved_tables()
        self.url_list.addItems(urls)

    def _on_select_saved(self, value: str) -> None:
        if value:
            self.url_input.setText(value)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PMS Chart Analyzer")
        self.resize(1100, 720)
        self.setAcceptDrops(True)
        self.parser = PMSParser()
        self.tabs = QTabWidget()
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
        set_path_action = QAction("beatoraja パスを指定", self)
        set_path_action.triggered.connect(self._select_beatoraja_path)
        settings_menu.addAction(set_path_action)

    def _select_beatoraja_path(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "beatoraja フォルダーを選択")
        if directory:
            config = load_config()
            config["beatoraja_path"] = directory
            save_config(config)
            QMessageBox.information(self, "保存", "beatoraja のパスを保存しました")

    def _load_config(self) -> None:
        config = load_config()
        if config.get("beatoraja_path"):
            self.statusBar().showMessage(f"beatoraja: {config['beatoraja_path']}")

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
                self.single_tab.load_file(path)
            else:
                QMessageBox.warning(self, "不正な形式", ".pms または .bms ファイルを指定してください")


def run_app() -> None:
    import sys

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


__all__ = ["MainWindow", "run_app"]
