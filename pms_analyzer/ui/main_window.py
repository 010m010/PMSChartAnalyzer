from __future__ import annotations

import html
import traceback
from pathlib import Path
from typing import Dict, List, Optional
from statistics import mean

from PyQt6.QtCore import QEvent, QThread, Qt, pyqtSignal, QUrl
from PyQt6.QtGui import QAction, QActionGroup, QDesktopServices, QDragEnterEvent, QDropEvent, QDragMoveEvent, QColor
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
from ..range_stats import calculate_range_selection_stats
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


def _metric_color(metric_key: str, value: float | None) -> QColor | None:
    if value is None:
        return None
    if metric_key == "terminal_difficulty":
        if value > 0.5:
            return QColor("#cc2f2f")
        if value > 0.2:
            return QColor("#e67a73")
        if value < -0.5:
            return QColor("#2f6bcc")
        if value < -0.2:
            return QColor("#74a2e6")
        return None
    if metric_key == "overall_difficulty":
        if value >= 1.0:
            return QColor("#cc2f2f")
        if value >= 0.7:
            return QColor("#e67a73")
        if value >= 0.3:
            return QColor("#f2b8b5")
        return None
    if metric_key == "gustiness":
        if value >= 3.0:
            return QColor("#cc2f2f")
        if value >= 2.0:
            return QColor("#e67a73")
        if value >= 1.0:
            return QColor("#f2b8b5")
        return None
    return None


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


class SortableTableWidgetItem(QTableWidgetItem):
    def __lt__(self, other: object) -> bool:
        if not isinstance(other, QTableWidgetItem):
            return super().__lt__(other)
        left = self.data(Qt.ItemDataRole.UserRole)
        right = other.data(Qt.ItemDataRole.UserRole)
        if left is not None and right is not None:
            try:
                return left < right
            except TypeError:
                pass
        return super().__lt__(other)


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
        self._latest_single_parse = None
        self._latest_single_density = None
        self._show_smoothed_line = True
        self.info_labels: Dict[str, QLabel] = {}
        self.metrics_labels: Dict[str, QLabel] = {}
        self.range_labels: Dict[str, QLabel] = {}
        self.status_label = QLabel(".pms ファイルをドラッグ＆ドロップしてください")
        self.file_label = QLabel("未選択")
        self.file_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self.file_label.setOpenExternalLinks(False)
        self.analyze_button = QPushButton("ファイルを開く")
        self._single_result_callback: Optional[callable[[str, DensityResult, int, Optional[float]], None]] = None
        self._worker: Optional[AnalysisWorker] = None
        self._current_path: Optional[Path] = None
        self._build_ui()

    def set_single_result_handler(self, handler: callable[[str, DensityResult, int, Optional[float]], None]) -> None:
        self._single_result_callback = handler

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout()

        file_layout = QHBoxLayout()
        file_layout.addWidget(self.analyze_button)
        file_layout.addWidget(QLabel("選択ファイル:"))
        self.file_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.file_label.setMinimumWidth(200)
        file_layout.addWidget(self.file_label, 1)
        main_layout.addLayout(file_layout)

        chart_container = QWidget()
        chart_layout = QVBoxLayout()
        chart_layout.setContentsMargins(0, 0, 0, 0)
        chart_layout.addWidget(self.chart)

        line_toggle_layout = QHBoxLayout()
        self.line_toggle_checkbox = QCheckBox("線グラフを表示")
        self.line_toggle_checkbox.setChecked(True)
        line_toggle_layout.addStretch()
        line_toggle_layout.addWidget(self.line_toggle_checkbox)
        chart_layout.addLayout(line_toggle_layout)

        chart_container.setLayout(chart_layout)

        bottom_container = QWidget()
        bottom_layout = QVBoxLayout()
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_container.setLayout(bottom_layout)

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
            value_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            value_label.setWordWrap(False)
            value_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            value_label.setToolTip("-")
            self.info_labels[key] = value_label
            info_grid.addWidget(value_label, row, 1)
        info_grid.setHorizontalSpacing(6)
        info_grid.setColumnMinimumWidth(0, 100)
        info_grid.setColumnMinimumWidth(1, 200)
        info_grid.setColumnStretch(0, 0)
        info_grid.setColumnStretch(1, 0)
        info_group.setLayout(info_grid)

        metrics_group = QGroupBox("密度メトリクス")
        grid = QGridLayout()
        labels = {
            "max_density": "秒間最大密度",
            "average_density": "平均密度",
            "rms_density": "RMS",
            "terminal_density": "終端密度",
            "terminal_rms_density": "終端RMS",
            "overall_difficulty": "全体難度数",
            "terminal_difficulty": "終端難度数",
            "gustiness": "突風度数",
        }
        for row, (key, title) in enumerate(labels.items()):
            lbl = QLabel(title)
            lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(lbl, row, 0)
            value_label = QLabel("-")
            value_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            value_label.setWordWrap(False)
            value_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            value_label.setToolTip("-")
            self.metrics_labels[key] = value_label
            grid.addWidget(value_label, row, 1)
        grid.setHorizontalSpacing(6)
        grid.setColumnMinimumWidth(0, 150)
        grid.setColumnMinimumWidth(1, 150)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 0)
        metrics_group.setLayout(grid)

        range_group = QGroupBox("選択範囲の統計")
        range_grid = QGridLayout()
        range_fields = [
            ("range_span", "範囲 (秒)"),
            ("range_notes", "NOTES数"),
            ("range_gauge", "ゲージ増加量"),
            ("range_avg", "平均密度"),
            ("range_rms", "RMS"),
        ]
        for row, (key, title) in enumerate(range_fields):
            lbl = QLabel(title)
            lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            range_grid.addWidget(lbl, row, 0)
            value_label = QLabel("-")
            value_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            value_label.setWordWrap(False)
            value_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            value_label.setToolTip("-")
            self.range_labels[key] = value_label
            range_grid.addWidget(value_label, row, 1)
        range_grid.setHorizontalSpacing(6)
        range_grid.setColumnMinimumWidth(0, 150)
        range_grid.setColumnMinimumWidth(1, 150)
        range_grid.setColumnStretch(0, 0)
        range_grid.setColumnStretch(1, 0)
        range_group.setLayout(range_grid)

        details_layout = QHBoxLayout()
        details_layout.addWidget(info_group, 2)
        details_layout.addWidget(metrics_group, 1)
        details_layout.addWidget(range_group, 1)

        bottom_layout.addLayout(details_layout)
        bottom_layout.addWidget(self.status_label)
        bottom_layout.addItem(QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(chart_container)
        splitter.addWidget(bottom_container)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)

        main_layout.addWidget(splitter)
        self.setLayout(main_layout)

        self._update_file_label(None)
        self.analyze_button.clicked.connect(self._open_file_dialog)
        self.line_toggle_checkbox.toggled.connect(self._on_toggle_smoothed_line)
        self.file_label.linkActivated.connect(self._open_current_folder)
        self.chart.set_selection_callback(self._on_range_selected)
        self._reset_range_metrics()

    def _set_label_text(self, label: QLabel, text: str) -> None:
        label.setText(text)
        label.setToolTip(text)

    def _apply_metric_label_colors(self, density: DensityResult) -> None:
        for key in ("overall_difficulty", "terminal_difficulty", "gustiness"):
            label = self.metrics_labels.get(key)
            if not label:
                continue
            color = _metric_color(key, getattr(density, key, None))
            if color:
                label.setStyleSheet(f"color: {color.name()}")
            else:
                label.setStyleSheet("")

    def set_theme_mode(self, mode: str) -> None:
        self.chart.set_theme_mode(mode)
        self.chart.draw()

    def _open_file_dialog(self) -> None:
        file_name, _ = QFileDialog.getOpenFileName(self, "PMS ファイルを開く", "", "PMS Files (*.pms *.bms)")
        if file_name:
            self.load_file(Path(file_name))

    def load_file(self, path: Path) -> None:
        self._current_path = path
        self._update_file_label(path)
        self.status_label.setText("解析中...")
        self._reset_range_metrics()
        self.chart.clear_selection()
        self._worker = AnalysisWorker(self.parser, path)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_finished(self, parse_result, density: DensityResult) -> None:
        self._latest_single_parse = parse_result
        self._latest_single_density = density
        title_text = self._render_density_chart()
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
                "overall_difficulty": density.overall_difficulty,
                "terminal_difficulty": density.terminal_difficulty,
                "gustiness": density.gustiness,
            },
        )
        append_history(record)
        if self._single_result_callback:
            self._single_result_callback(
                title_text,
                density,
                len(parse_result.notes),
                parse_result.total_value,
            )

    def _on_failed(self, error_message: str) -> None:
        self.status_label.setText("解析に失敗しました")
        QMessageBox.critical(self, "エラー", error_message)

    def _update_metrics(self, density: DensityResult) -> None:
        self._set_label_text(self.metrics_labels["max_density"], f"{density.max_density:.2f} note/s")
        self._set_label_text(self.metrics_labels["average_density"], f"{density.average_density:.2f} note/s")
        self._set_label_text(self.metrics_labels["rms_density"], f"{density.rms_density:.2f} note/s")
        self._set_label_text(self.metrics_labels["terminal_density"], f"{density.terminal_density:.2f} note/s")
        self._set_label_text(
            self.metrics_labels["terminal_rms_density"], f"{density.terminal_rms_density:.2f} note/s"
        )
        self._set_label_text(self.metrics_labels["overall_difficulty"], f"{density.overall_difficulty:.2f}")
        self._set_label_text(self.metrics_labels["terminal_difficulty"], f"{density.terminal_difficulty:.2f}")
        self._set_label_text(self.metrics_labels["gustiness"], f"{density.gustiness:.2f}")
        self._apply_metric_label_colors(density)
        self._reset_range_metrics()

    def _on_toggle_smoothed_line(self, checked: bool) -> None:
        self._show_smoothed_line = checked
        self._render_density_chart()

    def _render_density_chart(self) -> str:
        if not self._latest_single_density or not self._latest_single_parse:
            return ""
        parse_result = self._latest_single_parse
        density = self._latest_single_density
        title_text = parse_result.title
        if parse_result.subtitle:
            title_text = f"{parse_result.title} {parse_result.subtitle}"
        self.chart.plot(
            density.per_second_by_key,
            title=title_text,
            total_time=density.duration,
            terminal_window=density.terminal_window,
            show_smoothed_line=self._show_smoothed_line,
            preserve_selection=True,
        )
        return title_text

    def _update_file_label(self, path: Optional[Path]) -> None:
        if path and path.exists():
            folder = path.parent
            escaped_path = html.escape(str(path))
            folder_url = QUrl.fromLocalFile(str(folder)).toString()
            escaped_folder_url = html.escape(folder_url)
            self.file_label.setText(f'<a href="{escaped_folder_url}">{escaped_path}</a>')
            self.file_label.setToolTip(str(path))
        elif path:
            text = str(path)
            self.file_label.setText(text)
            self.file_label.setToolTip(text)
        else:
            self.file_label.setText("未選択")
            self.file_label.setToolTip("未選択")

    def _open_current_folder(self, url: str | None = None) -> None:
        if url:
            QDesktopServices.openUrl(QUrl(url))
            return
        if not self._current_path:
            return
        folder = self._current_path.parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _update_info(self, parse_result) -> None:
        def _set_text(key: str, text: str, *, color: str | None = None) -> None:
            label = self.info_labels.get(key)
            if not label:
                return
            self._set_label_text(label, text)
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

    def _reset_range_metrics(self) -> None:
        defaults = {
            "range_span": "-",
            "range_notes": "-",
            "range_gauge": "-",
            "range_avg": "-",
            "range_rms": "-",
        }
        for key, default in defaults.items():
            label = self.range_labels.get(key)
            if label:
                self._set_label_text(label, default)

    def _on_range_selected(self, start: float, end: float) -> None:
        if not self._latest_single_parse or not self._latest_single_density:
            self._reset_range_metrics()
            return
        density = self._latest_single_density
        parse_result = self._latest_single_parse
        if not density.per_second_total:
            self._reset_range_metrics()
            return
        total_bins = len(density.per_second_total)
        bin_size = density.duration / total_bins if total_bins else 1.0
        start_clamped = max(min(start, end), 0.0)
        end_clamped = min(max(start, end), float(total_bins))
        start_seconds_display = start_clamped * bin_size
        end_seconds_display = end_clamped * bin_size
        if end_clamped <= start_clamped:
            self._reset_range_metrics()
            if "range_span" in self.range_labels:
                self._set_label_text(
                    self.range_labels["range_span"],
                    f"{int(round(start_seconds_display))}～{int(round(end_seconds_display))} 秒",
                )
            return

        first_note_time = parse_result.notes[0].time if parse_result.notes else 0.0
        note_count = sum(
            1 for note in parse_result.notes if start_clamped <= note.time - first_note_time < end_clamped
        )
        duration = end_clamped - start_clamped
        avg_density = note_count / duration if duration > 0 else 0.0

        gauge_increase = None
        if parse_result.total_value is not None and parse_result.notes:
            gauge_rate = parse_result.total_value / len(parse_result.notes)
            gauge_increase = gauge_rate * note_count

        stats = calculate_range_selection_stats(
            density.per_second_total,
            density.duration,
            parse_result.notes,
            parse_result.total_value,
            start,
            end,
            bin_size=bin_size,
        )

        if not stats:
            self._reset_range_metrics()
            return

        if "range_span" in self.range_labels:
            self._set_label_text(
                self.range_labels["range_span"],
                f"{int(round(stats.start_seconds))}～{int(round(stats.end_seconds))} 秒",
            )
        if "range_notes" in self.range_labels:
            self._set_label_text(self.range_labels["range_notes"], str(stats.note_count))
        if "range_gauge" in self.range_labels:
            gauge_text = "未定義" if stats.gauge_increase is None else f"{stats.gauge_increase:.2f}"
            self._set_label_text(self.range_labels["range_gauge"], gauge_text)
        if "range_avg" in self.range_labels:
            self._set_label_text(self.range_labels["range_avg"], f"{stats.average_density:.2f} note/s")
        if "range_rms" in self.range_labels:
            self._set_label_text(self.range_labels["range_rms"], f"{stats.rms_density:.2f} note/s")

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
        self.table_widget = QTableWidget(0, 16)
        self.table_widget.setHorizontalHeaderLabels(
            [
                "LEVEL",
                "曲名",
                "NOTES数",
                "TOTAL値",
                "増加率",
                "最大瞬間密度",
                "平均密度",
                "RMS",
                "終端密度",
                "終端RMS",
                "全体難度数",
                "終端難度数",
                "突風度数",
                "md5",
                "sha256",
                "Path",
            ]
        )
        self.table_widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_widget.setSortingEnabled(True)
        header = self.table_widget.horizontalHeader()
        header.setSortIndicatorShown(True)
        header.setSortIndicator(0, Qt.SortOrder.AscendingOrder)
        header.setSectionsClickable(True)
        self.table_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        v_header = self.table_widget.verticalHeader()
        v_header.setDefaultSectionSize(20)
        v_header.setMinimumSectionSize(18)
        self.load_button = QPushButton("読み込む")
        self.analyze_button = QPushButton("更新")
        self.delete_button = QPushButton("削除")
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://example.com/table.json など")
        self.url_list = QComboBox()
        self.url_list.setEditable(False)
        self.metric_selector = QComboBox()
        self.metric_selector.addItems(
            ["NOTES数", "最大瞬間密度", "平均密度", "RMS", "終端密度", "終端RMS", "全体難度数", "終端難度数", "突風度数"]
        )
        self.chart_type_selector = QComboBox()
        self.chart_type_selector.addItems(["箱ひげ図", "散布図"])
        self.scale_min_input = QLineEdit()
        self.scale_min_input.setPlaceholderText("縦軸の最小値")
        self.scale_max_input = QLineEdit()
        self.scale_max_input.setPlaceholderText("縦軸の最大値")
        self.scale_button = QPushButton("更新")
        self.scale_reset_button = QPushButton("リセット")
        self._manual_y_min: float | None = None
        self._manual_y_max: float | None = None
        self.summary_metric_selector = QComboBox()
        self.summary_metric_selector.addItems(
            [
                "NOTES数",
                "増加率",
                "最大瞬間密度",
                "平均密度",
                "RMS",
                "終端密度",
                "終端RMS",
                "全体難度数",
                "終端難度数",
                "突風度数",
            ]
        )
        self.filter_button = QPushButton("絞り込み")
        self._filter_selection: set[str] = set()
        self.summary_table = QTableWidget(0, 8)
        self.summary_table.setHorizontalHeaderLabels(
            ["LEVEL", "解析済み譜面数", "平均", "最小", "Q1", "中央値", "Q3", "最大"]
        )
        self.summary_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        summary_v_header = self.summary_table.verticalHeader()
        summary_v_header.setDefaultSectionSize(20)
        summary_v_header.setMinimumSectionSize(18)
        self.songdata_label = QLabel("songdata.db: 未設定")
        self.single_overlay_checkbox = QCheckBox("単曲分析の値を表示")
        self.single_overlay_checkbox.setChecked(True)
        self._single_overlay_title: str | None = None
        self._single_overlay_density: DensityResult | None = None
        self._single_overlay_note_count: int | None = None
        self._single_overlay_total_value: float | None = None
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

    def update_single_overlay(
        self, title: str, density: DensityResult, note_count: int, total_value: Optional[float]
    ) -> None:
        self._single_overlay_title = title
        self._single_overlay_density = density
        self._single_overlay_note_count = note_count
        self._single_overlay_total_value = total_value
        self._refresh_chart_only()

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

        chart_container = QWidget()
        chart_layout = QVBoxLayout()
        chart_layout.setContentsMargins(0, 0, 0, 0)
        chart_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        metric_layout = QHBoxLayout()
        metric_layout.addWidget(self.filter_button)
        metric_layout.addStretch()
        metric_layout.addWidget(QLabel("縦軸:"))
        metric_layout.addWidget(self.metric_selector)
        metric_layout.addWidget(QLabel("グラフ:"))
        metric_layout.addWidget(self.chart_type_selector)
        metric_layout.addWidget(QLabel("スケール調整:"))
        metric_layout.addWidget(self.scale_min_input)
        metric_layout.addWidget(QLabel("～"))
        metric_layout.addWidget(self.scale_max_input)
        metric_layout.addWidget(self.scale_button)
        metric_layout.addWidget(self.scale_reset_button)

        chart_area = QWidget()
        chart_area_layout = QVBoxLayout()
        chart_area_layout.setContentsMargins(0, 0, 0, 0)
        chart_area_layout.addLayout(metric_layout)
        chart_area_layout.addWidget(self.difficulty_chart)
        chart_area_layout.addWidget(self.box_chart)
        overlay_toggle_layout = QHBoxLayout()
        overlay_toggle_layout.addStretch()
        overlay_toggle_layout.addWidget(self.single_overlay_checkbox)
        chart_area_layout.addLayout(overlay_toggle_layout)
        chart_area.setLayout(chart_area_layout)

        chart_layout.addWidget(chart_area)
        chart_container.setLayout(chart_layout)

        table_tabs = QTabWidget()

        table_tab = QWidget()
        table_tab_layout = QVBoxLayout()
        table_tab_layout.setContentsMargins(0, 0, 0, 0)
        table_tab_layout.addWidget(self.table_widget)
        table_tab.setLayout(table_tab_layout)

        summary_tab = QWidget()
        summary_layout = QVBoxLayout()
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_header = QHBoxLayout()
        summary_header.addWidget(QLabel("項目:"))
        summary_header.addWidget(self.summary_metric_selector)
        summary_header.addStretch()
        summary_layout.addLayout(summary_header)
        summary_layout.addWidget(self.summary_table)
        summary_tab.setLayout(summary_layout)

        table_tabs.addTab(table_tab, "譜面一覧")
        table_tabs.addTab(summary_tab, "難易度統計")

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(chart_container)
        splitter.addWidget(table_tabs)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        layout.addWidget(splitter)
        self.setLayout(layout)

        self.load_button.clicked.connect(self._select_table)
        self.analyze_button.clicked.connect(self._analyze_table)
        self.url_list.currentTextChanged.connect(self._on_select_saved)
        self.metric_selector.currentTextChanged.connect(self._refresh_chart_only)
        self.chart_type_selector.currentTextChanged.connect(lambda: self._refresh_chart_only(clear_scale=True))
        self.summary_metric_selector.currentTextChanged.connect(self._render_summary)
        self.scale_button.clicked.connect(self._apply_manual_scale)
        self.scale_reset_button.clicked.connect(self._reset_manual_scale)
        self.delete_button.clicked.connect(self._delete_saved)
        self.filter_button.clicked.connect(self._open_filter_dialog)
        self.table_widget.customContextMenuRequested.connect(self._show_table_context_menu)
        self.single_overlay_checkbox.toggled.connect(self._refresh_chart_only)
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
                self._reset_sorting_safe()
                self._sync_filter_options()
                self._apply_filter_defaults()

    def _on_select_saved(self, value: str) -> None:
        if value:
            if value in self._cached_results:
                self._latest_analyses = self._cached_results[value]
                self._current_symbol = self._cached_symbols.get(value, "")
                self._render_table_and_chart()
                self._reset_sorting_safe()
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
            self._manual_y_min = None
            self._manual_y_max = None
            self.scale_min_input.clear()
            self.scale_max_input.clear()
        if not self._latest_analyses:
            return
        self._render_chart()

    def _render_table_and_chart(self) -> None:
        self._sync_filter_options()
        self._apply_filter_defaults()
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

            level_item = SortableTableWidgetItem(difficulty_display)
            level_sort_value = float(level_key[1]) if isinstance(level_key[1], (int, float)) else difficulty_display
            level_item.setData(Qt.ItemDataRole.UserRole, level_sort_value)
            self.table_widget.setItem(row, 0, level_item)
            title_item = SortableTableWidgetItem(title_text)
            title_item.setData(Qt.ItemDataRole.UserRole, title_text)
            if not analysis.resolved_path:
                title_item.setForeground(QColor("red"))
                title_item.setText(f"{title_text}（未解析）")
            self.table_widget.setItem(row, 1, title_item)
            notes_item = SortableTableWidgetItem(str(analysis.note_count or 0))
            notes_item.setData(Qt.ItemDataRole.UserRole, float(analysis.note_count or 0))
            self.table_widget.setItem(row, 2, notes_item)
            if analysis.total_value is None:
                total_item = SortableTableWidgetItem("未定義")
                total_item.setForeground(QColor("red"))
                total_item.setData(Qt.ItemDataRole.UserRole, float("-inf"))
            else:
                total_item = SortableTableWidgetItem(f"{analysis.total_value:.2f}")
                total_item.setData(Qt.ItemDataRole.UserRole, float(analysis.total_value))
            self.table_widget.setItem(row, 3, total_item)
            rate_item = SortableTableWidgetItem(rate)
            rate_value = float(rate) if rate != "-" else float("-inf")
            rate_item.setData(Qt.ItemDataRole.UserRole, rate_value)
            self.table_widget.setItem(row, 4, rate_item)
            max_item = SortableTableWidgetItem(f"{density.max_density:.2f}")
            max_item.setData(Qt.ItemDataRole.UserRole, float(density.max_density))
            self.table_widget.setItem(row, 5, max_item)
            avg_item = SortableTableWidgetItem(f"{density.average_density:.2f}")
            avg_item.setData(Qt.ItemDataRole.UserRole, float(density.average_density))
            self.table_widget.setItem(row, 6, avg_item)
            rms_item = SortableTableWidgetItem(f"{density.rms_density:.2f}")
            rms_item.setData(Qt.ItemDataRole.UserRole, float(density.rms_density))
            self.table_widget.setItem(row, 7, rms_item)
            term_item = SortableTableWidgetItem(f"{density.terminal_density:.2f}")
            term_item.setData(Qt.ItemDataRole.UserRole, float(density.terminal_density))
            self.table_widget.setItem(row, 8, term_item)
            term_rms_item = SortableTableWidgetItem(f"{density.terminal_rms_density:.2f}")
            term_rms_item.setData(Qt.ItemDataRole.UserRole, float(density.terminal_rms_density))
            self.table_widget.setItem(row, 9, term_rms_item)
            overall_item = SortableTableWidgetItem(f"{density.overall_difficulty:.2f}")
            overall_item.setData(Qt.ItemDataRole.UserRole, float(density.overall_difficulty))
            self._apply_metric_item_color(overall_item, "overall_difficulty", density.overall_difficulty)
            self.table_widget.setItem(row, 10, overall_item)
            terminal_diff_item = SortableTableWidgetItem(f"{density.terminal_difficulty:.2f}")
            terminal_diff_item.setData(Qt.ItemDataRole.UserRole, float(density.terminal_difficulty))
            self._apply_metric_item_color(terminal_diff_item, "terminal_difficulty", density.terminal_difficulty)
            self.table_widget.setItem(row, 11, terminal_diff_item)
            gust_item = SortableTableWidgetItem(f"{density.gustiness:.2f}")
            gust_item.setData(Qt.ItemDataRole.UserRole, float(density.gustiness))
            self._apply_metric_item_color(gust_item, "gustiness", density.gustiness)
            self.table_widget.setItem(row, 12, gust_item)
            md5_item = SortableTableWidgetItem(analysis.md5 or "")
            md5_item.setData(Qt.ItemDataRole.UserRole, analysis.md5 or "")
            self.table_widget.setItem(row, 13, md5_item)
            sha_item = SortableTableWidgetItem(analysis.sha256 or "")
            sha_item.setData(Qt.ItemDataRole.UserRole, analysis.sha256 or "")
            self.table_widget.setItem(row, 14, sha_item)
            path_text = str(analysis.resolved_path) if analysis.resolved_path else ""
            path_item = SortableTableWidgetItem(path_text)
            path_item.setData(Qt.ItemDataRole.UserRole, path_text)
            self.table_widget.setItem(row, 15, path_item)

        self.table_widget.setSortingEnabled(sorting_state)
        if sorting_state and current_sort:
            self.table_widget.sortItems(*current_sort)
        else:
            # Default sort by LEVEL using numeric key
            self.table_widget.sortItems(0, Qt.SortOrder.AscendingOrder)
        self._render_chart()
        self._render_summary()

    def _reset_sorting_safe(self) -> None:
        """Reset the sort indicator without raising if the helper is missing.

        Some interactions (e.g., toggling UI elements mid-selection) could
        trigger this logic before the table is fully constructed in earlier
        builds. Guard the call so we gracefully keep the default sort instead
        of crashing.
        """
        if hasattr(self, "_reset_sorting"):
            reset_method = getattr(self, "_reset_sorting")
            if callable(reset_method):
                reset_method()
                return
        header = self.table_widget.horizontalHeader()
        if header:
            self.table_widget.setSortingEnabled(False)
            header.setSortIndicator(0, Qt.SortOrder.AscendingOrder)
            self.table_widget.setSortingEnabled(True)
            self.table_widget.sortItems(0, Qt.SortOrder.AscendingOrder)

    def _reset_sorting(self) -> None:
        header = self.table_widget.horizontalHeader()
        self.table_widget.setSortingEnabled(False)
        header.setSortIndicator(0, Qt.SortOrder.AscendingOrder)
        self.table_widget.setSortingEnabled(True)
        self.table_widget.sortItems(0, Qt.SortOrder.AscendingOrder)

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
        all_values: list[float] = []
        for key in ordered_keys:
            for v in data[key]:
                scatter_points.append((key, v))
                all_values.append(v)
        overlay_line = None
        overlay_value = None
        if self.single_overlay_checkbox.isChecked():
            overlay_value = self._overlay_value_for_metric(metric)
            if overlay_value is not None and self._single_overlay_title:
                overlay_line = (overlay_value, f"{self._single_overlay_title} ({metric})", "#6AC59B")
                all_values.append(overlay_value)
        y_limits = self._determine_y_limits(all_values)

        # Toggle charts
        if self.chart_type_selector.currentText() == "箱ひげ図":
            self.difficulty_chart.hide()
            self.box_chart.show()
            box_data = {k: data[k] for k in ordered_keys}
            self.box_chart.plot(box_data, metric, y_limits=y_limits, overlay_line=overlay_line)
        else:
            self.box_chart.hide()
            self.difficulty_chart.show()
            self.difficulty_chart.plot(
                scatter_points,
                y_label=metric,
                order=ordered_keys,
                sort_key=difficulty_sort_key,
                y_limits=y_limits,
                overlay_line=overlay_line,
            )

    def _metric_value(self, analysis: ChartAnalysis, metric: str) -> float | None:
        density = analysis.density
        if metric == "NOTES数":
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
        if metric == "全体難度数":
            return density.overall_difficulty
        if metric == "終端難度数":
            return density.terminal_difficulty
        if metric == "突風度数":
            return density.gustiness
        if metric == "増加率":
            if analysis.total_value is not None and analysis.note_count:
                return analysis.total_value / analysis.note_count
            return None
        return None

    def _apply_metric_item_color(self, item: QTableWidgetItem, metric_key: str, value: float | None) -> None:
        color = _metric_color(metric_key, value)
        if color:
            item.setForeground(color)

    def _overlay_value_for_metric(self, metric: str) -> float | None:
        if not self._single_overlay_density:
            return None
        density = self._single_overlay_density
        if metric == "NOTES数":
            return float(self._single_overlay_note_count or 0)
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
        if metric == "全体難度数":
            return density.overall_difficulty
        if metric == "終端難度数":
            return density.terminal_difficulty
        if metric == "突風度数":
            return density.gustiness
        if metric == "増加率":
            if self._single_overlay_total_value is not None and self._single_overlay_note_count:
                return self._single_overlay_total_value / self._single_overlay_note_count
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
        lower = low - padding
        upper = high + padding
        if global_min >= 0 and lower < 0:
            lower = max(0.0, global_min - padding * 0.5)
        return (lower, upper)

    def _determine_y_limits(self, values: List[float]) -> Optional[tuple[float, float]]:
        if self._manual_y_min is None and self._manual_y_max is None:
            return None
        auto_limits = self._compute_y_limits(values) if values else None
        lower = self._manual_y_min if self._manual_y_min is not None else (auto_limits[0] if auto_limits else 0.0)
        upper = self._manual_y_max if self._manual_y_max is not None else (
            auto_limits[1] if auto_limits else (lower + 1.0)
        )
        if values and all(val >= 0 for val in values) and lower < 0:
            lower = 0.0
        if lower == upper:
            upper = lower + 1.0
        return (lower, upper)

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
        min_text = self.scale_min_input.text().strip()
        max_text = self.scale_max_input.text().strip()
        if not min_text and not max_text:
            self._manual_y_min = None
            self._manual_y_max = None
            self._refresh_chart_only()
            return
        try:
            min_value = float(min_text) if min_text else None
            max_value = float(max_text) if max_text else None
            if min_value is not None and max_value is not None and min_value >= max_value:
                raise ValueError
            self._manual_y_min = min_value
            self._manual_y_max = max_value
        except ValueError:
            QMessageBox.warning(self, "不正な値", "数値を正しく入力し、最小値は最大値より小さくしてください")
            return
        self._refresh_chart_only()

    def _reset_manual_scale(self) -> None:
        self.scale_min_input.clear()
        self.scale_max_input.clear()
        self._manual_y_min = None
        self._manual_y_max = None
        self._refresh_chart_only()

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
        if self._available_levels and not self._filter_selection:
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
        self.single_tab.set_single_result_handler(self.table_tab.update_single_overlay)
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
