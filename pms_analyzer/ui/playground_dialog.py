from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QIntValidator, QMouseEvent, QPainter, QPalette
from PyQt6.QtWidgets import (
    QAbstractScrollArea,
    QApplication,
    QDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..analysis import DensityResult
from ..theme import apply_app_palette
from .charts import StackedDensityChart


BIN_SIZE_SECONDS = 1.0
MAX_SECONDS = 150
MAX_DENSITY = 30
DEFAULT_TOTAL = 300
GAUGE_GOAL = 85.0
GAUGE_INITIAL = 2.0


@dataclass
class PlaygroundResult:
    density: DensityResult
    per_second_by_key: List[List[int]]
    total_time_for_chart: float
    terminal_window_for_chart: float | None
    total_notes: int
    gauge_rate: float | None


class FreehandDensityCanvas(QWidget):
    bars_updated = pyqtSignal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAutoFillBackground(True)
        self._bars: list[int] = [0 for _ in range(MAX_SECONDS)]
        self._drawing = False
        self._last_second: int | None = None
        self._last_density: int | None = None

    def bars(self) -> list[int]:
        return list(self._bars)

    def clear(self) -> None:
        self._bars = [0 for _ in range(MAX_SECONDS)]
        self._drawing = False
        self._last_second = None
        self._last_density = None
        self.update()
        self.bars_updated.emit(self.bars())

    def set_bars(self, values: list[int]) -> None:
        length = min(len(values), MAX_SECONDS)
        for idx in range(length):
            self._bars[idx] = max(0, min(values[idx], MAX_DENSITY))
        self.update()
        self.bars_updated.emit(self.bars())

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._drawing = True
            self._apply_point(event.position().x(), event.position().y())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if self._drawing:
            self._apply_point(event.position().x(), event.position().y())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if self._drawing:
            self._drawing = False
            self._last_second = None
            self._last_density = None
            self.bars_updated.emit(self.bars())
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        if self._drawing:
            self._drawing = False
            self._last_second = None
            self._last_density = None
            self.bars_updated.emit(self.bars())
        super().leaveEvent(event)

    def _apply_point(self, x: float, y: float) -> None:
        width = max(self.width(), 1)
        height = max(self.height(), 1)
        sec_float = max(0.0, min(x / width, 0.9999)) * (MAX_SECONDS - 1)
        sec_index = int(round(sec_float))
        density_ratio = 1.0 - max(0.0, min(y / height, 1.0))
        density = int(round(density_ratio * MAX_DENSITY))
        density = max(0, min(density, MAX_DENSITY))

        if self._last_second is None:
            indices = [sec_index]
        else:
            step = 1 if sec_index >= self._last_second else -1
            indices = list(range(self._last_second, sec_index + step, step))
        for idx in indices:
            ratio = 1.0
            if self._last_second is not None and idx != sec_index:
                distance = abs(sec_index - self._last_second)
                if distance > 0:
                    offset = abs(idx - self._last_second) / distance
                    start_val = self._last_density if self._last_density is not None else density
                    ratio = start_val + (density - start_val) * offset
            else:
                ratio = density
            self._bars[idx] = int(round(max(0.0, min(ratio, MAX_DENSITY))))

        self._last_second = sec_index
        self._last_density = density
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        palette = self.palette()
        painter.fillRect(self.rect(), palette.brush(QPalette.ColorRole.Base))

        width = max(self.width(), 1)
        height = max(self.height(), 1)
        bar_width = width / MAX_SECONDS
        painter.setPen(palette.color(QPalette.ColorRole.Mid))
        for x in range(0, MAX_SECONDS + 1, 10):
            xpos = int(round(x * bar_width))
            painter.drawLine(xpos, 0, xpos, height)
        for y in range(0, MAX_DENSITY + 1, 5):
            ypos = int(round(height - (y / MAX_DENSITY) * height))
            painter.drawLine(0, ypos, width, ypos)

        painter.setPen(palette.color(QPalette.ColorRole.Highlight))
        painter.setBrush(palette.brush(QPalette.ColorRole.Highlight))
        for idx, value in enumerate(self._bars):
            bar_height = (value / MAX_DENSITY) * height
            x_pos = int(round(idx * bar_width))
            painter.drawRect(x_pos, int(round(height - bar_height)), int(round(bar_width)), int(round(bar_height)))


def _per_second_by_key_from_total(per_second_total: list[int]) -> list[list[int]]:
    per_second_by_key: list[list[int]] = []
    for count in per_second_total:
        row = [0 for _ in range(9)]
        row[0] = count
        per_second_by_key.append(row)
    return per_second_by_key


def compute_playground_density(per_second_total: list[int], total_value: int | None) -> PlaygroundResult:
    epsilon = 1e-6
    total_notes = sum(per_second_total)
    first_idx = next((i for i, val in enumerate(per_second_total) if val > 0), None)
    if first_idx is None:
        empty_by_key = _per_second_by_key_from_total(per_second_total)
        density = DensityResult(
            per_second_total=per_second_total,
            per_second_by_key=empty_by_key,
            max_density=0.0,
            average_density=0.0,
            cms_density=0.0,
            chm_density=0.0,
            terminal_density=0.0,
            terminal_rms_density=0.0,
            terminal_cms_density=0.0,
            terminal_chm_density=0.0,
            rms_density=0.0,
            duration=0.0,
            terminal_window=None,
            overall_difficulty=0.0,
            terminal_difficulty=0.0,
            terminal_difficulty_cms=0.0,
            terminal_difficulty_chm=0.0,
            terminal_density_difference=0.0,
            gustiness=0.0,
            terminal_gustiness=0.0,
        )
        return PlaygroundResult(
            density=density,
            per_second_by_key=empty_by_key,
            total_time_for_chart=len(per_second_total) * BIN_SIZE_SECONDS,
            terminal_window_for_chart=None,
            total_notes=0,
            gauge_rate=None,
        )

    last_idx = max(idx for idx, val in enumerate(per_second_total) if val > 0)
    trimmed = per_second_total[first_idx : last_idx + 1]
    non_zero_bins = [val for val in trimmed if val > 0]
    duration = len(trimmed) * BIN_SIZE_SECONDS

    max_density = max(trimmed)
    average_density = sum(non_zero_bins) / len(non_zero_bins) if non_zero_bins else 0.0

    terminal_density = 0.0
    terminal_rms_density = 0.0
    terminal_cms_density = 0.0
    terminal_chm_density = 0.0
    terminal_density_difference = 0.0
    terminal_max_density = 0.0
    terminal_gustiness = 0.0
    terminal_window_used: float | None = None
    terminal_start_bin = len(trimmed)
    gauge_rate = None

    if total_value is not None and total_notes > 0:
        gauge_rate = total_value / total_notes
        if gauge_rate > 0:
            required_notes = ceil((GAUGE_GOAL - GAUGE_INITIAL) / gauge_rate)
            start_note_index = max(total_notes - required_notes, 0)
            cumulative = 0
            for idx, val in enumerate(trimmed):
                cumulative += val
                if cumulative > start_note_index:
                    terminal_start_bin = idx
                    break
            terminal_bins = trimmed[terminal_start_bin:] if terminal_start_bin < len(trimmed) else []
            terminal_window_used = len(terminal_bins) * BIN_SIZE_SECONDS if terminal_bins else 0.0
            note_count_terminal = sum(terminal_bins)
            if terminal_window_used and terminal_window_used > 0 and note_count_terminal > 0:
                terminal_density = note_count_terminal / terminal_window_used
            terminal_max_density = max(terminal_bins) if terminal_bins else 0.0
            terminal_bins_non_zero = [val for val in terminal_bins if val > 0]
            if terminal_bins_non_zero:
                terminal_rms_density = (
                    sum(val * val for val in terminal_bins_non_zero) / len(terminal_bins_non_zero)
                ) ** 0.5
                terminal_cms_density = (
                    sum(val**3 for val in terminal_bins_non_zero) / len(terminal_bins_non_zero)
                ) ** (1.0 / 3.0)
                terminal_chm_density = sum(val * val for val in terminal_bins_non_zero) / sum(terminal_bins_non_zero)
                terminal_mean = sum(terminal_bins_non_zero) / len(terminal_bins_non_zero)
                variance = sum((val - terminal_mean) ** 2 for val in terminal_bins_non_zero) / len(terminal_bins_non_zero)
                std_dev = variance**0.5
                if std_dev > 0:
                    terminal_gustiness = (terminal_max_density - terminal_mean) / (std_dev + epsilon)

    rms_density = (
        (sum(val * val for val in non_zero_bins) / len(non_zero_bins)) ** 0.5
        if non_zero_bins
        else 0.0
    )
    cms_density = (
        (sum(val**3 for val in non_zero_bins) / len(non_zero_bins)) ** (1.0 / 3.0)
        if non_zero_bins
        else 0.0
    )
    chm_density = sum(val * val for val in non_zero_bins) / sum(non_zero_bins) if non_zero_bins else 0.0

    mean_per_second = sum(non_zero_bins) / len(non_zero_bins) if non_zero_bins else 0.0
    variance = (
        sum((val - mean_per_second) ** 2 for val in non_zero_bins) / len(non_zero_bins)
        if non_zero_bins
        else 0.0
    )
    std_per_second = variance**0.5

    non_terminal_bins = trimmed[:terminal_start_bin]
    non_terminal_bins_non_zero = [val for val in non_terminal_bins if val > 0]
    non_terminal_rms = (
        (sum(val * val for val in non_terminal_bins_non_zero) / len(non_terminal_bins_non_zero)) ** 0.5
        if non_terminal_bins_non_zero
        else rms_density
    )
    non_terminal_cms = (
        (sum(val**3 for val in non_terminal_bins_non_zero) / len(non_terminal_bins_non_zero)) ** (1.0 / 3.0)
        if non_terminal_bins_non_zero
        else cms_density
    )
    non_terminal_chm = (
        sum(val * val for val in non_terminal_bins_non_zero) / sum(non_terminal_bins_non_zero)
        if non_terminal_bins_non_zero and sum(non_terminal_bins_non_zero) > 0
        else chm_density
    )

    overall_difficulty = mean_per_second / (std_per_second + epsilon) if mean_per_second > 0 else 0.0
    terminal_difficulty = (
        (terminal_rms_density - non_terminal_rms) / (std_per_second + epsilon) if std_per_second > 0 else 0.0
    )
    terminal_difficulty_cms = (
        (terminal_cms_density - non_terminal_cms) / (std_per_second + epsilon) if std_per_second > 0 else 0.0
    )
    terminal_difficulty_chm = (
        (terminal_chm_density - non_terminal_chm) / (std_per_second + epsilon) if std_per_second > 0 else 0.0
    )
    if terminal_window_used is not None:
        terminal_density_difference = terminal_chm_density - non_terminal_chm
    gustiness = (max_density - mean_per_second) / (std_per_second + epsilon) if std_per_second > 0 else 0.0
    if terminal_window_used is None:
        terminal_gustiness = 0.0

    density = DensityResult(
        per_second_total=per_second_total,
        per_second_by_key=_per_second_by_key_from_total(per_second_total),
        max_density=max_density,
        average_density=average_density,
        cms_density=cms_density,
        chm_density=chm_density,
        terminal_density=terminal_density,
        terminal_rms_density=terminal_rms_density,
        terminal_cms_density=terminal_cms_density,
        terminal_chm_density=terminal_chm_density,
        rms_density=rms_density,
        duration=duration,
        terminal_window=terminal_window_used,
        overall_difficulty=overall_difficulty,
        terminal_difficulty=terminal_difficulty,
        terminal_difficulty_cms=terminal_difficulty_cms,
        terminal_difficulty_chm=terminal_difficulty_chm,
        terminal_density_difference=terminal_density_difference,
        gustiness=gustiness,
        terminal_gustiness=terminal_gustiness,
    )

    total_time_for_chart = (last_idx + 1) * BIN_SIZE_SECONDS
    terminal_window_for_chart = terminal_window_used
    return PlaygroundResult(
        density=density,
        per_second_by_key=_per_second_by_key_from_total(per_second_total),
        total_time_for_chart=total_time_for_chart,
        terminal_window_for_chart=terminal_window_for_chart,
        total_notes=total_notes,
        gauge_rate=gauge_rate,
    )


class PlaygroundDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, *, theme_mode: str = "system") -> None:
        super().__init__(parent)
        self.setWindowTitle("用語・指標について")
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.theme_mode = theme_mode
        self._current_total = DEFAULT_TOTAL
        self._result: PlaygroundResult | None = None
        self._build_ui()
        self._apply_theme(theme_mode)
        self._update_metrics_labels(None, None)

    def _build_ui(self) -> None:
        layout = QVBoxLayout()
        tabs = QTabWidget()
        tabs.addTab(self._build_explanation_tab(), "説明")
        tabs.addTab(self._build_play_tab(), "プレイエリア")
        tabs.currentChanged.connect(lambda _: self._reset_tab_scroll(tabs))
        layout.addWidget(tabs)
        self.setLayout(layout)
        self._tabs = tabs

    def _reset_tab_scroll(self, tabs: QTabWidget) -> None:
        widget = tabs.currentWidget()
        if isinstance(widget, QScrollArea):
            widget.verticalScrollBar().setValue(0)
        else:
            scrolls = widget.findChildren(QScrollArea)
            for scroll in scrolls:
                scroll.verticalScrollBar().setValue(0)

    def _build_explanation_tab(self) -> QWidget:
        container = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        vbox = QVBoxLayout()
        header = QLabel("指標の定義と計算方法")
        font: QFont = header.font()
        font.setPointSize(font.pointSize() + 1)
        font.setBold(True)
        header.setFont(font)
        vbox.addWidget(header)

        sections = [
            (
                "密度の計算方法",
                "1 秒ビンでノーツ数を集計し、0 ノーツの区間は平均計算から除外します。"
                " 終端範囲は TOTAL に基づき必要ノーツ数を末尾から逆算して決定します。",
            ),
            ("平均密度", "非ゼロビンの平均値。`average = sum(density) / count`"),
            ("体感密度 (CHM)", "二乗平均/一次平均で求める体感指標。`chm = Σn^2 / Σn`"),
            ("終端範囲", "必要ノーツ数ぶん末尾側の区間。単曲分析と同じ算出ロジック/色でハイライトします。"),
            ("終端密度/終端体感密度", "終端範囲内での平均密度と CHM。"),
            ("全体難度数", "平均密度を標準偏差で割った指標。"),
            ("突風度数", "ピーク密度と平均密度の差を標準偏差で正規化。`(max-avg)/std`"),
            ("終端突風度数", "終端範囲内の突風度数。"),
            ("終端密度差", "終端 CHM と非終端 CHM の差。"),
        ]

        for title, desc in sections:
            title_label = QLabel(title)
            title_font = title_label.font()
            title_font.setBold(True)
            title_label.setFont(title_font)
            body = QLabel(desc)
            body.setWordWrap(True)
            vbox.addWidget(title_label)
            vbox.addWidget(body)

        vbox.addItem(QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))
        inner.setLayout(vbox)
        scroll.setWidget(inner)
        return scroll

    def _build_play_tab(self) -> QWidget:
        container = QWidget()
        outer = QVBoxLayout()

        control_layout = QHBoxLayout()
        total_label = QLabel("TOTAL")
        self.total_input = QLineEdit(str(DEFAULT_TOTAL))
        self.total_input.setValidator(QIntValidator(1, 1000, self))
        self.total_input.setPlaceholderText("1～1000 (未入力時は 300)")
        self.total_status = QLabel("1～1000 の整数を入力してください")
        self.total_status.setStyleSheet("color: gray;")
        control_layout.addWidget(total_label)
        control_layout.addWidget(self.total_input)
        clear_button = QPushButton("クリア")
        control_layout.addWidget(clear_button)
        control_layout.addStretch()
        control_layout.addWidget(self.total_status)
        outer.addLayout(control_layout)

        self.canvas = FreehandDensityCanvas(self)
        outer.addWidget(self.canvas)

        self.chart = StackedDensityChart(self)
        outer.addWidget(self.chart)

        metrics_group = self._build_metrics_group()
        outer.addWidget(metrics_group)

        outer.addItem(QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))
        container.setLayout(outer)

        self.canvas.bars_updated.connect(self._on_bars_updated)
        self.total_input.editingFinished.connect(self._on_total_changed)
        clear_button.clicked.connect(self.canvas.clear)
        return container

    def _build_metrics_group(self) -> QWidget:
        group = QGroupBox("パラメータ")
        grid = QGridLayout()
        self.metric_labels: Dict[str, QLabel] = {}

        left_labels = [
            ("notes", "NOTES数"),
            ("rate", "増加率 (/notes)"),
            ("max_density", "最大瞬間密度"),
        ]
        center_labels = [
            ("average_density", "平均密度"),
            ("chm_density", "体感密度"),
            ("terminal_density", "終端密度"),
            ("terminal_chm_density", "終端体感密度"),
        ]
        right_labels = [
            ("overall_difficulty", "全体難度数"),
            ("gustiness", "突風度数"),
            ("terminal_gustiness", "終端突風度数"),
            ("terminal_density_difference", "終端密度差"),
        ]

        for row, (key, label) in enumerate(left_labels):
            grid.addWidget(QLabel(label), row, 0)
            value = QLabel("-")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(value, row, 1)
            self.metric_labels[key] = value

        for row, (key, label) in enumerate(center_labels):
            grid.addWidget(QLabel(label), row, 2)
            value = QLabel("-")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(value, row, 3)
            self.metric_labels[key] = value

        for row, (key, label) in enumerate(right_labels):
            grid.addWidget(QLabel(label), row, 4)
            value = QLabel("-")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(value, row, 5)
            self.metric_labels[key] = value

        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        grid.setColumnStretch(5, 1)
        group.setLayout(grid)
        return group

    def _on_total_changed(self) -> None:
        total_value = self._parse_total()
        if total_value is None:
            self.total_status.setText("未入力/不正のため 300 を適用しました")
            self.total_status.setStyleSheet("color: #cc2f2f;")
            self._current_total = DEFAULT_TOTAL
            self.total_input.setText(str(DEFAULT_TOTAL))
        else:
            self.total_status.setText("1～1000 の整数を入力してください")
            self.total_status.setStyleSheet("color: gray;")
            self._current_total = total_value
        self._recompute()

    def _on_bars_updated(self, bars: list[int]) -> None:
        self._recompute(bars)

    def _parse_total(self) -> int | None:
        text = self.total_input.text().strip()
        if not text:
            return None
        try:
            value = int(text)
        except ValueError:
            return None
        if 1 <= value <= 1000:
            return value
        return None

    def _recompute(self, bars: Optional[list[int]] = None) -> None:
        per_second = bars if bars is not None else self.canvas.bars()
        result = compute_playground_density(per_second, self._current_total)
        self._result = result
        self._render_chart(result)
        self._update_metrics_labels(result.density, result.gauge_rate)

    def _render_chart(self, result: PlaygroundResult) -> None:
        self.chart.plot(
            result.per_second_by_key,
            title="用語・指標について",
            total_time=result.total_time_for_chart,
            terminal_window=result.terminal_window_for_chart,
            show_smoothed_line=True,
        )

    def _update_metrics_labels(self, density: DensityResult | None, gauge_rate: float | None) -> None:
        def set_text(key: str, text: str) -> None:
            label = self.metric_labels.get(key)
            if label:
                label.setText(text)
                label.setToolTip(text)

        if not density:
            for label in self.metric_labels.values():
                label.setText("-")
                label.setToolTip("-")
            return

        set_text("notes", f"{sum(density.per_second_total)}")
        rate_text = "-" if gauge_rate is None else f"{gauge_rate:.3f}"
        set_text("rate", rate_text)
        set_text("max_density", f"{density.max_density:.0f} note/s")
        set_text("average_density", f"{density.average_density:.2f} note/s")
        set_text("chm_density", f"{density.chm_density:.2f} note/s")
        terminal_available = density.terminal_window is not None and density.terminal_window > 0
        set_text("terminal_density", "-" if not terminal_available else f"{density.terminal_density:.2f} note/s")
        set_text(
            "terminal_chm_density",
            "-" if not terminal_available else f"{density.terminal_chm_density:.2f} note/s",
        )
        set_text("overall_difficulty", f"{density.overall_difficulty:.2f}")
        set_text("gustiness", f"{density.gustiness:.2f}")
        set_text("terminal_gustiness", "-" if not terminal_available else f"{density.terminal_gustiness:.2f}")
        density_diff_text = "-" if not terminal_available else f"{density.terminal_density_difference:.2f}"
        set_text("terminal_density_difference", density_diff_text)

    def _apply_theme(self, mode: str) -> None:
        app = QApplication.instance()
        if app:
            apply_app_palette(app, mode)
        self.chart.set_theme_mode(mode)

    def set_theme_mode(self, mode: str) -> None:
        self.theme_mode = mode
        self._apply_theme(mode)
