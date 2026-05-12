from __future__ import annotations

import html
import warnings
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

import matplotlib
from matplotlib.backend_bases import MouseButton
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.figure import Figure
from matplotlib import cm, rcParams
from matplotlib.widgets import SpanSelector
import numpy as np
from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtGui import QCursor, QPalette, QGuiApplication
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout

from ..theme import system_prefers_dark

# Prefer Windows-installed Meiryo to avoid missing font warnings; fall back to common JP fonts.
rcParams["font.family"] = ["Meiryo", "Yu Gothic", "MS Gothic", "sans-serif"]

matplotlib.use("Agg")

ThemeMode = str  # "system", "light", "dark"


@dataclass(frozen=True)
class ScatterPointInfo:
    title: str
    level: str
    y_label: str
    y_value: str
    path: str | None = None
    x_label: str | None = None
    x_value: str | None = None


@dataclass(frozen=True)
class _HoverPoint:
    x: float
    y: float
    info: ScatterPointInfo


class _ScatterPointPopup(QFrame):
    def __init__(self, parent, open_callback: Callable[[str], None]) -> None:
        super().__init__(parent)
        self._open_callback = open_callback
        self._current_path: str | None = None
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self.label = QLabel(self)
        self.label.setTextFormat(Qt.TextFormat.RichText)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.label.setOpenExternalLinks(False)
        self.label.linkActivated.connect(self._on_link_activated)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.addWidget(self.label)
        self.hide()

    def show_info(self, info: ScatterPointInfo, global_pos: QPoint, *, dark: bool) -> None:
        self._current_path = info.path
        text_color = "#E6E6E6" if dark else "#1D2835"
        bg_color = "#2A2A2A" if dark else "#FFFFFF"
        border_color = "#666666" if dark else "#B7C3D0"
        link_color = "#8FD2FF" if dark else "#1F68B3"
        self.setStyleSheet(
            f"""
            QFrame {{
                background-color: {bg_color};
                border: 1px solid {border_color};
                border-radius: 6px;
            }}
            QLabel {{
                color: {text_color};
                background: transparent;
                border: none;
            }}
            """
        )

        def row(label: str, value: str) -> str:
            return f"<div><b>{html.escape(label)}</b>: {value}</div>"

        title = html.escape(info.title or "(untitled)")
        if info.path:
            title = (
                f'<a href="open" style="color: {link_color}; '
                f'text-decoration: underline;">{title}</a>'
            )
        rows = [row("TITLE", title), row("LEVEL", html.escape(info.level))]
        if info.x_label and info.x_value is not None:
            rows.append(row(info.x_label, html.escape(info.x_value)))
        rows.append(row(info.y_label, html.escape(info.y_value)))
        self.label.setText("".join(rows))
        self.adjustSize()

        parent = self.parentWidget()
        if parent is None:
            return
        local = parent.mapFromGlobal(global_pos) + QPoint(14, 14)
        max_x = max(0, parent.width() - self.width() - 4)
        max_y = max(0, parent.height() - self.height() - 4)
        if local.x() > max_x:
            local.setX(max(4, parent.mapFromGlobal(global_pos).x() - self.width() - 14))
        if local.y() > max_y:
            local.setY(max(4, parent.mapFromGlobal(global_pos).y() - self.height() - 14))
        self.move(max(4, min(local.x(), max_x)), max(4, min(local.y(), max_y)))
        self.raise_()
        self.show()

    def _on_link_activated(self, _url: str) -> None:
        if self._current_path:
            self.hide()
            self._open_callback(self._current_path)


class _ScatterHoverController:
    def __init__(self, canvas: FigureCanvasQTAgg, ax) -> None:
        self.canvas = canvas
        self.ax = ax
        self.points: list[_HoverPoint] = []
        self._data_xy = np.empty((0, 2), dtype=float)
        self._open_callback: Callable[[str], None] | None = None
        self._active_index: int | None = None
        self._selected_index: int | None = None
        self._selection_artist = None
        self._radius_px = 8.0
        self._popup = _ScatterPointPopup(canvas, self._open_path)
        self._hide_timer = QTimer(canvas)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._hide_if_cursor_outside)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.canvas.mpl_connect("button_press_event", self._on_button_press)
        self.canvas.mpl_connect("figure_leave_event", lambda _event: self._schedule_hide())

    def set_open_callback(self, callback: Callable[[str], None] | None) -> None:
        self._open_callback = callback

    def set_points(self, points: list[_HoverPoint]) -> None:
        self.reset()
        self.points = points
        if points:
            self._data_xy = np.array([(point.x, point.y) for point in points], dtype=float)
        else:
            self._data_xy = np.empty((0, 2), dtype=float)

    def reset(self) -> None:
        self._active_index = None
        self._selected_index = None
        self._remove_selection_artist()
        self._popup.hide()

    def hide(self) -> None:
        if self._selected_index is not None:
            return
        self._active_index = None
        self._popup.hide()

    def clear_selection(self) -> None:
        self._selected_index = None
        self._active_index = None
        self._remove_selection_artist()
        self._popup.hide()
        self.canvas.draw_idle()

    def _open_path(self, path: str) -> None:
        self.clear_selection()
        if self._open_callback:
            self._open_callback(path)

    def _on_motion(self, event) -> None:
        if self._selected_index is not None:
            return
        if event.inaxes is not self.ax:
            self.hide()
            return
        index = self._nearest_index(event)
        if index is None:
            self.hide()
            return
        if index == self._active_index and self._popup.isVisible():
            return
        self._active_index = index
        self._popup.show_info(self.points[index].info, QCursor.pos(), dark=self._is_dark_mode())

    def _on_button_press(self, event) -> None:
        if getattr(event, "button", None) not in (MouseButton.LEFT, 1):
            return
        if event.inaxes is not self.ax:
            self.clear_selection()
            return
        index = self._nearest_index(event)
        if index is None:
            self.clear_selection()
            return
        self._select_index(index)

    def _nearest_index(self, event) -> int | None:
        if not self.points:
            return None
        display = self.ax.transData.transform(self._data_xy)
        distances = (display[:, 0] - event.x) ** 2 + (display[:, 1] - event.y) ** 2
        index = int(np.argmin(distances))
        if float(distances[index]) <= self._radius_px**2:
            return index
        return None

    def _select_index(self, index: int) -> None:
        self._selected_index = index
        self._active_index = index
        self._draw_selection_artist(index)
        self._popup.show_info(self.points[index].info, QCursor.pos(), dark=self._is_dark_mode())

    def _draw_selection_artist(self, index: int) -> None:
        self._remove_selection_artist()
        point = self.points[index]
        x_limits = self.ax.get_xlim()
        y_limits = self.ax.get_ylim()
        edge_color = "#FFE08A" if self._is_dark_mode() else "#D14C1F"
        self._selection_artist = self.ax.scatter(
            [point.x],
            [point.y],
            s=96,
            facecolors="none",
            edgecolors=edge_color,
            linewidths=1.8,
            zorder=8,
        )
        self.ax.set_xlim(*x_limits)
        self.ax.set_ylim(*y_limits)
        self.canvas.draw_idle()

    def _remove_selection_artist(self) -> None:
        if self._selection_artist is None:
            return
        try:
            self._selection_artist.remove()
        except ValueError:
            pass
        self._selection_artist = None

    def _schedule_hide(self) -> None:
        if self._selected_index is None:
            self._hide_timer.start(180)

    def _hide_if_cursor_outside(self) -> None:
        if self._selected_index is not None:
            return
        pos = QCursor.pos()
        canvas_pos = self.canvas.mapFromGlobal(pos)
        popup_pos = self._popup.mapFromGlobal(pos)
        if self.canvas.rect().contains(canvas_pos) or self._popup.rect().contains(popup_pos):
            return
        self.hide()

    def _is_dark_mode(self) -> bool:
        chart = self.canvas
        if hasattr(chart, "_is_dark_mode"):
            return bool(chart._is_dark_mode())
        return False


def _normalized_point_infos(
    points: list[object],
    point_infos: Optional[List[ScatterPointInfo]],
) -> list[ScatterPointInfo | None]:
    infos: list[ScatterPointInfo | None] = list(point_infos or [])
    if len(infos) < len(points):
        infos.extend([None] * (len(points) - len(infos)))
    return infos[: len(points)]

DARK_DENSITY_CMAP = LinearSegmentedColormap.from_list(
    "density_dark",
    [
        "#D6E676",  # yellow-green
        "#6AD18C",  # bright green
        "#1BA7A0",  # blue-green
    ],
    N=10,
)

class StackedDensityChart(FigureCanvasQTAgg):
    def __init__(self, parent=None):  # type: ignore[override]
        self.figure = Figure(figsize=(8, 3))
        self.ax = self.figure.add_subplot(111)
        super().__init__(self.figure)
        self.setParent(parent)
        self.theme_mode: ThemeMode = "system"
        self._style_axes(dark=self._is_dark_mode())
        self._bars = None
        self._bar_width: float = 0.9
        self._edge_margin_px: float = 14.0
        self._bar_colors: list[str] = []
        self._selection_callback: Optional[Callable[[float, float], None]] = None
        self._selection_artist = None
        self._selection_enabled = True
        self._x_limits: tuple[float, float] | None = None
        self._selected_bins: tuple[int, int] | None = None
        self._last_plot_state: dict[str, object] | None = None
        self._resize_debounce_timer = QTimer(self)
        self._resize_debounce_timer.setSingleShot(True)
        self._resize_debounce_timer.timeout.connect(lambda: self._handle_resize_redraw())
        self._span_selector = SpanSelector(
            self.ax,
            self._on_span_select,
            "horizontal",
            useblit=True,
            props={"facecolor": "#66ccff", "alpha": 0.15},
            interactive=True,
        )

    def _is_dark_mode(self) -> bool:
        if self.theme_mode == "dark":
            return True
        if self.theme_mode == "light":
            return False
        if QGuiApplication.instance():
            return system_prefers_dark()
        palette = self.palette()
        window_color = palette.color(QPalette.ColorRole.Window)
        return window_color.lightness() < 128

    def set_theme_mode(self, mode: ThemeMode) -> None:
        self.theme_mode = mode
        self._style_axes(dark=self._is_dark_mode())
        self._redraw_last_plot(preserve_selection=True)

    def _style_axes(self, *, dark: bool) -> None:
        face = "#1f1f1f" if dark else "#f2f4f8"
        text = "#e6e6e6" if dark else "#1D2835"
        grid = "#555555" if dark else "#b8c5d3"
        border = "#9fb4c9" if dark else "#556075"
        accent = "#7CC7FF" if dark else "#2F7ACC"

        self.figure.set_facecolor(face)
        self.ax.set_facecolor(face)
        self.ax.tick_params(axis="x", colors=text)
        self.ax.tick_params(axis="y", colors=text)
        for spine in self.ax.spines.values():
            spine.set_visible(True)
            spine.set_color(border)
            spine.set_linewidth(1.0)
        self.ax.set_xlabel("Seconds", color=text)
        self.ax.set_ylabel("Notes", color=text)
        self.ax.grid(color=grid, linestyle=":", linewidth=0.7)
        self.ax.tick_params(axis="x", labelcolor=text)
        self.ax.tick_params(axis="y", labelcolor=text)
        self.ax.title.set_color(text)
        self._line_color = accent

    def plot(
        self,
        per_second_by_key: List[List[int]],
        title: str | None = None,
        *,
        total_time: float | None = None,
        terminal_window: float | None = None,
        y_max: float | None = None,
        show_smoothed_line: bool = True,
        preserve_selection: bool = False,
    ) -> None:
        self._last_plot_state = {
            "per_second_by_key": per_second_by_key,
            "title": title,
            "total_time": total_time,
            "terminal_window": terminal_window,
            "y_max": y_max,
            "show_smoothed_line": show_smoothed_line,
        }
        saved_selection = self._selected_bins if preserve_selection else None
        self._clear_selection(reset_saved=not preserve_selection)
        self.ax.clear()
        dark = self._is_dark_mode()
        self._style_axes(dark=dark)
        if not per_second_by_key:
            self.draw()
            return
        self._bar_colors = []

        totals = [sum(row) for row in per_second_by_key]
        x = list(range(len(per_second_by_key)))
        colors = [self._color_for_density(val, dark=dark) for val in totals]
        self._bar_colors = colors
        self._bars = self.ax.bar(x, totals, color=colors, width=self._bar_width)
        grid = "#555555" if dark else "#b8c5d3"
        self.ax.grid(color=grid, linestyle=":", linewidth=0.7)
        if title is not None:
            self.ax.set_title(title, color="#e6e6e6" if dark else "#1D2835")
        if total_time and terminal_window:
            start = max(total_time - terminal_window, 0)
            start_bin = int(start)
            end_bin = len(per_second_by_key)
            face = "#8A6F1F" if dark else "#E8C96A"
            label_color = "#F7E5A2" if dark else "#473000"
            start_edge = max(start_bin - 0.5, -0.5)
            end_edge = end_bin - 0.5
            self.ax.axvspan(start_edge, end_edge, color=face, alpha=0.3, zorder=0)
            self.ax.text(
                max(start_edge + 0.2, 0.0),
                self.ax.get_ylim()[1] * 0.9,
                "終端範囲",
                color=label_color,
                fontsize=9,
                bbox=dict(facecolor=face, alpha=0.45, edgecolor="none", boxstyle="round,pad=0.2"),
            )
        smoothed = self._smooth_density_wave(totals)
        if show_smoothed_line and smoothed:
            line_color = "#1F6FD1" if not dark else "#7CC7FF"
            self.ax.plot(
                x,
                smoothed,
                color=self._line_color,
                linewidth=2.4,
                alpha=0.9,
                zorder=3,
            )
        if y_max:
            self.ax.set_ylim(top=y_max)
        self.figure.tight_layout()
        self._set_x_limits(len(per_second_by_key))
        self.figure.tight_layout()
        if preserve_selection and saved_selection:
            self._draw_selection_region(*saved_selection, update_saved=True)
        else:
            self.draw()

    def _color_for_density(self, density: int, *, dark: bool) -> str:
        # Bucket every 10 density and map to a perceptually-uniform colormap
        bucket = min(density // 10, 9)
        cmap = DARK_DENSITY_CMAP if dark else cm.get_cmap("plasma", 10)
        r, g, b, _ = cmap(bucket)
        return f"#{int(r*255):02X}{int(g*255):02X}{int(b*255):02X}"

    def set_selection_callback(self, callback: Optional[Callable[[float, float], None]]) -> None:
        self._selection_callback = callback

    def set_selection_enabled(self, enabled: bool) -> None:
        self._selection_enabled = enabled
        if self._span_selector:
            try:
                self._span_selector.set_active(enabled)
            except Exception:
                pass
        if not enabled:
            self._clear_selection()

    def clear_selection(self) -> None:
        self._clear_selection()

    def _on_span_select(self, x_min: float, x_max: float) -> None:
        if not self._selection_enabled:
            return
        if x_min is None or x_max is None:
            return
        span_start, span_end = sorted([x_min, x_max])
        start_bin = int(np.ceil(span_start + self._bar_width / 2))
        end_inclusive = int(np.floor(span_end - self._bar_width / 2))
        if self._bars:
            max_index = len(self._bars) - 1
            start_bin = max(0, min(start_bin, max_index))
            end_inclusive = max(start_bin, min(end_inclusive, max_index))
        end_bin = end_inclusive + 1
        if end_bin <= start_bin:
            self._clear_selection()
            return
        self._draw_selection_region(start_bin, end_bin, update_saved=True)
        if self._selection_callback:
            self._selection_callback(float(start_bin), float(end_bin))

    def _draw_selection_region(self, start_bin: int, end_bin: int, *, update_saved: bool = False) -> None:
        max_bin = len(self._bars) if self._bars else 0
        if max_bin:
            start_bin = max(min(start_bin, max_bin - 1), 0)
            end_bin = max(start_bin + 1, min(end_bin, max_bin))
        if update_saved:
            self._selected_bins = (start_bin, end_bin)
        if self._selection_artist:
            try:
                self._selection_artist.remove()
            except (ValueError, NotImplementedError):
                # Some artist types cannot be removed; just hide them.
                self._selection_artist.set_visible(False)
        face = "#4EB2FF" if not self._is_dark_mode() else "#2E8BC0"
        start_edge = start_bin - 0.5
        end_edge = end_bin - 0.5
        self._selection_artist = self.ax.axvspan(start_edge, end_edge, color=face, alpha=0.2, zorder=0)
        self._apply_bar_highlight(start_bin, end_bin)
        self._restore_x_limits()
        self.draw_idle()

    def _clear_selection(self, *, reset_saved: bool = True) -> None:
        if self._span_selector:
            try:
                self._span_selector.clear()
            except Exception:
                # Fallback for matplotlib versions where clear might not be available
                pass
        if self._selection_artist:
            try:
                self._selection_artist.remove()
            except (ValueError, NotImplementedError):
                self._selection_artist.set_visible(False)
            self._selection_artist = None
        if reset_saved:
            self._selected_bins = None
        self._reset_bar_geometry()
        if self._bars:
            for patch, color in zip(self._bars, self._bar_colors):
                patch.set_color(color)
        self._restore_x_limits()
        self.draw_idle()

    def _apply_bar_highlight(self, start_bin: int, end_bin: int) -> None:
        if not self._bars:
            return
        self._reset_bar_geometry()
        for idx, patch in enumerate(self._bars):
            if idx < len(self._bar_colors):
                base_color = self._bar_colors[idx]
            else:
                base_color = patch.get_facecolor()
            if start_bin <= idx < end_bin:
                patch.set_color("#3BA7FF")
            else:
                patch.set_color(base_color)

    def _reset_bar_geometry(self) -> None:
        if not self._bars:
            return
        for idx, patch in enumerate(self._bars):
            patch.set_width(self._bar_width)
            patch.set_x(idx - self._bar_width / 2)

    def _smooth_density_wave(self, totals: list[int]) -> list[float]:
        if not totals:
            return []
        if len(totals) < 3:
            return [float(val) for val in totals]
        window_length = self._adaptive_window_length(len(totals), totals)
        polyorder = min(3, window_length - 1)
        smoothed = self._savgol_smooth(np.array(totals, dtype=float), window_length, polyorder)
        gaussian_sigma = 1.2 if len(totals) < 120 else 1.5
        smoothed = self._gaussian_smooth(smoothed, sigma=gaussian_sigma)
        return smoothed.tolist()

    def _adaptive_window_length(self, length: int, totals: list[int]) -> int:
        """Choose a smoothing window that keeps short spikes visible.

        秒間密度の線グラフでは 1〜3 秒程度の局所的な山を埋もれさせないことが
        重要なので、窓幅は以前よりも小さく、最大でも 7 秒程度に抑える。
        変化が大きい譜面では窓幅をさらに縮め、鋭いピークを残す。
        """
        if length < 5:
            base = length if length % 2 == 1 else length - 1
            return max(base, 3)

        diffs = np.abs(np.diff(totals)) if len(totals) > 1 else np.array([0.0])
        normalized_variation = float(np.percentile(diffs, 75)) / (float(np.mean(totals)) + 1e-6)
        growth = max(0, min(3, length // 60))
        window = 5 + growth

        if normalized_variation < 0.15:
            window += 2
        if normalized_variation < 0.05:
            window += 1

        window = min(window, 11)

        if window >= length:
            window = length if length % 2 == 1 else length - 1
        if window < 3:
            return 3
        if window % 2 == 0:
            window -= 1
        return window

    def _gaussian_smooth(self, values: np.ndarray, *, sigma: float) -> np.ndarray:
        if sigma <= 0:
            return values
        radius = max(1, int(3 * sigma))
        x = np.arange(-radius, radius + 1, dtype=float)
        kernel = np.exp(-(x**2) / (2 * sigma**2))
        kernel /= kernel.sum()
        padded = np.pad(values, (radius, radius), mode="edge")
        return np.convolve(padded, kernel, mode="valid")

    def _savgol_smooth(self, values: np.ndarray, window_length: int, polyorder: int) -> np.ndarray:
        half_window = window_length // 2
        padded = np.pad(values, (half_window, half_window), mode="edge")
        x = np.arange(-half_window, half_window + 1, dtype=float)
        smoothed = np.empty_like(values, dtype=float)
        for idx in range(len(values)):
            segment = padded[idx : idx + window_length]
            coeffs = np.polyfit(x, segment, polyorder)
            smoothed[idx] = np.polyval(coeffs, 0.0)
        return smoothed

    def _get_renderer(self):
        renderer = self.figure.canvas.get_renderer() if self.figure.canvas else None
        if renderer is None:
            self.figure.canvas.draw()
            renderer = self.figure.canvas.get_renderer()
        return renderer

    def _pixel_margin_to_data_units(self, margin_px: float, num_bins: int) -> float:
        if margin_px <= 0:
            return 0.0
        renderer = self._get_renderer()
        try:
            bbox = self.ax.get_window_extent(renderer=renderer)
            axis_width_px = bbox.width
        except Exception:
            axis_width_px = 0.0
        if axis_width_px <= 0:
            return 0.35
        visible_bins = max(float(num_bins), 1.0)
        data_per_px = visible_bins / axis_width_px
        return margin_px * data_per_px

    def _set_x_limits(self, num_bins: int) -> None:
        margin = self._pixel_margin_to_data_units(self._edge_margin_px, num_bins)
        if num_bins <= 0:
            self._x_limits = (-0.5 - margin, 0.5 + margin)
        else:
            self._x_limits = (-0.5 - margin, num_bins - 0.5 + margin)
        self.ax.set_xlim(self._x_limits)
        self.ax.set_autoscalex_on(False)

    def _restore_x_limits(self) -> None:
        if self._x_limits:
            self.ax.set_xlim(self._x_limits)
            self.ax.set_autoscalex_on(False)

    def _redraw_last_plot(self, *, preserve_selection: bool = False) -> None:
        if not self._last_plot_state:
            self.draw_idle()
            return
        self.plot(
            self._last_plot_state["per_second_by_key"],
            title=self._last_plot_state["title"],
            total_time=self._last_plot_state["total_time"],
            terminal_window=self._last_plot_state["terminal_window"],
            y_max=self._last_plot_state["y_max"],
            show_smoothed_line=self._last_plot_state["show_smoothed_line"],
            preserve_selection=preserve_selection,
        )

    def _handle_resize_redraw(self) -> None:
        self.figure.tight_layout()
        self._redraw_last_plot(preserve_selection=True)

    def _schedule_resize_redraw(self) -> None:
        self._resize_debounce_timer.start(180)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._schedule_resize_redraw()


class BoxPlotCanvas(FigureCanvasQTAgg):
    def __init__(self, parent=None):  # type: ignore[override]
        self.figure = Figure(figsize=(6, 4))
        self.ax = self.figure.add_subplot(111)
        super().__init__(self.figure)
        self.setParent(parent)
        self.theme_mode: ThemeMode = "system"
        self._last_plot_state: dict[str, object] | None = None
        self._resize_debounce_timer = QTimer(self)
        self._resize_debounce_timer.setSingleShot(True)
        self._resize_debounce_timer.timeout.connect(self._handle_resize_redraw)

    def _is_dark_mode(self) -> bool:
        if self.theme_mode == "dark":
            return True
        if self.theme_mode == "light":
            return False
        if QGuiApplication.instance():
            return system_prefers_dark()
        palette = self.palette()
        window_color = palette.color(QPalette.ColorRole.Window)
        return window_color.lightness() < 128

    def set_theme_mode(self, mode: ThemeMode) -> None:
        self.theme_mode = mode
        self._style_axes(dark=self._is_dark_mode())
        self._redraw_last_plot()

    def _style_axes(self, *, dark: bool) -> None:
        face = "#1f1f1f" if dark else "#f2f4f8"
        text = "#e6e6e6" if dark else "#1D2835"
        grid = "#555555" if dark else "#b8c5d3"
        border = "#9fb4c9" if dark else "#556075"
        self.figure.set_facecolor(face)
        self.ax.set_facecolor(face)
        self.ax.tick_params(axis="x", colors=text, rotation=45)
        self.ax.tick_params(axis="y", colors=text)
        for spine in self.ax.spines.values():
            spine.set_visible(True)
            spine.set_color(border)
            spine.set_linewidth(1.0)
        self.ax.set_title(self.ax.get_title(), color=text)
        self.ax.set_ylabel(self.ax.get_ylabel(), color=text)
        self.ax.grid(True, linestyle=":", linewidth=0.7, color=grid)

    def plot(
        self,
        values: Dict[str, List[float]],
        metric_name: str,
        *,
        y_limits: Optional[tuple[float, float]] = None,
        overlay_line: Optional[tuple[float, str, str]] = None,
    ) -> None:
        self._last_plot_state = {
            "values": values,
            "metric_name": metric_name,
            "y_limits": y_limits,
            "overlay_line": overlay_line,
        }
        self.ax.clear()
        dark = self._is_dark_mode()
        if not values:
            self.draw()
            return

        labels = list(values.keys())
        data = [values[label] for label in labels]
        colors = {
            "edge": "#7CC7FF" if dark else "#004A80",
            "fill": "#1F3A5A" if dark else "#B3D9FF",
            "median": "#FFD27F" if dark else "#CC6600",
        }
        bp = self.ax.boxplot(
            data,
            labels=labels,
            vert=True,
            patch_artist=True,
            boxprops=dict(facecolor=colors["fill"], edgecolor=colors["edge"]),
            medianprops=dict(color=colors["median"]),
            whiskerprops=dict(color=colors["edge"]),
            capprops=dict(color=colors["edge"]),
            flierprops=dict(markeredgecolor=colors["edge"], markerfacecolor=colors["fill"]),
        )
        for patch in bp["boxes"]:
            patch.set_alpha(0.8)
        self.ax.set_title(f"{metric_name} の分布")
        self.ax.set_ylabel(metric_name)
        self._style_axes(dark=dark)
        if y_limits:
            self.ax.set_ylim(*y_limits)
        if overlay_line:
            value, label, color = overlay_line
            self.ax.axhline(value, color=color, linestyle="-", linewidth=1.1, label=label)
            legend = self.ax.legend(facecolor="#2A2A2A" if dark else "#FFFFFF", framealpha=0.85, loc="upper left")
            for text in legend.get_texts():
                text.set_color("#E6E6E6" if dark else "#1D2835")
        self.figure.tight_layout()
        self.draw()

    def _redraw_last_plot(self) -> None:
        if not self._last_plot_state:
            self.draw_idle()
            return
        self.plot(
            self._last_plot_state["values"],
            self._last_plot_state["metric_name"],
            y_limits=self._last_plot_state["y_limits"],
            overlay_line=self._last_plot_state["overlay_line"],
        )

    def _handle_resize_redraw(self) -> None:
        self.figure.tight_layout()
        self._redraw_last_plot()

    def _schedule_resize_redraw(self) -> None:
        self._resize_debounce_timer.start(180)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._schedule_resize_redraw()


class DifficultyScatterChart(FigureCanvasQTAgg):
    def __init__(self, parent=None):  # type: ignore[override]
        self.figure = Figure(figsize=(7, 3))
        self.ax = self.figure.add_subplot(111)
        super().__init__(self.figure)
        self.setParent(parent)
        self.theme_mode: ThemeMode = "system"
        self._style_axes(dark=self._is_dark_mode())
        self._last_plot_state: dict[str, object] | None = None
        self._hover = _ScatterHoverController(self, self.ax)
        self._resize_debounce_timer = QTimer(self)
        self._resize_debounce_timer.setSingleShot(True)
        self._resize_debounce_timer.timeout.connect(self._handle_resize_redraw)

    def _is_dark_mode(self) -> bool:
        if self.theme_mode == "dark":
            return True
        if self.theme_mode == "light":
            return False
        if QGuiApplication.instance():
            return system_prefers_dark()
        palette = self.palette()
        window_color = palette.color(QPalette.ColorRole.Window)
        return window_color.lightness() < 128

    def set_theme_mode(self, mode: ThemeMode) -> None:
        self.theme_mode = mode
        self._style_axes(dark=self._is_dark_mode())
        self._redraw_last_plot()

    def set_open_point_callback(self, callback: Callable[[str], None] | None) -> None:
        self._hover.set_open_callback(callback)

    def _style_axes(self, y_label: str = "密度", *, dark: bool) -> None:
        face = "#1f1f1f" if dark else "#f2f4f8"
        text = "#e6e6e6" if dark else "#1D2835"
        grid = "#555555" if dark else "#b8c5d3"
        border = "#9fb4c9" if dark else "#556075"
        self.figure.set_facecolor(face)
        self.ax.set_facecolor(face)
        self.ax.tick_params(axis="x", colors=text, rotation=45)
        self.ax.tick_params(axis="y", colors=text)
        for spine in self.ax.spines.values():
            spine.set_visible(True)
            spine.set_color(border)
            spine.set_linewidth(1.0)
        self.ax.set_xlabel("難易度", color=text)
        self.ax.set_ylabel(y_label, color=text)
        self.ax.grid(color=grid, linestyle=":", linewidth=0.7)

    def plot(
        self,
        points: List[tuple[str, float]],
        *,
        y_label: str = "密度",
        order: Optional[List[str]] = None,
        sort_key: Optional[Callable[[str], object]] = None,
        y_limits: Optional[tuple[float, float]] = None,
        overlay_line: Optional[tuple[float, str, str]] = None,
        point_infos: Optional[List[ScatterPointInfo]] = None,
    ) -> None:
        self._last_plot_state = {
            "points": points,
            "y_label": y_label,
            "order": order,
            "sort_key": sort_key,
            "y_limits": y_limits,
            "overlay_line": overlay_line,
            "point_infos": point_infos,
        }
        self._hover.reset()
        self.ax.clear()
        dark = self._is_dark_mode()
        self._style_axes(y_label=y_label, dark=dark)
        if not points:
            self._hover.set_points([])
            self.draw()
            return

        diffs = [p[0] for p in points]
        unique = order if order is not None else sorted({d for d in diffs}, key=sort_key or (lambda x: x))
        pos_map = {val: idx for idx, val in enumerate(unique)}
        infos = _normalized_point_infos(points, point_infos)
        filtered = [(d, den, info) for (d, den), info in zip(points, infos) if d in pos_map]
        x = [pos_map[d] for d, _, _ in filtered]
        y_vals = [den for _, den, _ in filtered]
        marker_color = "#7CC7FF" if dark else "#2F7ACC"
        self.ax.scatter(x, y_vals, c=marker_color, alpha=0.85)
        self._hover.set_points(
            [
                _HoverPoint(float(x_val), float(y_val), info)
                for x_val, y_val, info in zip(x, y_vals, [info for _, _, info in filtered])
                if info is not None
            ]
        )
        self.ax.set_xticks(list(pos_map.values()), labels=unique)
        grid = "#555555" if dark else "#b8c5d3"
        self.ax.grid(color=grid, linestyle=":", linewidth=0.7)
        if y_limits:
            self.ax.set_ylim(*y_limits)
        if overlay_line:
            value, label, color = overlay_line
            self.ax.axhline(value, color=color, linestyle="-", linewidth=1.1, label=label)
            legend = self.ax.legend(facecolor="#2A2A2A" if dark else "#FFFFFF", framealpha=0.85, loc="upper left")
            for text in legend.get_texts():
                text.set_color("#E6E6E6" if dark else "#1D2835")
        self.figure.tight_layout()
        self.draw()

    def _color_for_density(self, density: float) -> str:
        bucket = min(int(density // 10), 9)
        cmap = cm.get_cmap("plasma", 10)
        r, g, b, _ = cmap(bucket)
        return f"#{int(r*255):02X}{int(g*255):02X}{int(b*255):02X}"

    def _redraw_last_plot(self) -> None:
        if not self._last_plot_state:
            self.draw_idle()
            return
        self.plot(
            self._last_plot_state["points"],
            y_label=self._last_plot_state["y_label"],
            order=self._last_plot_state["order"],
            sort_key=self._last_plot_state["sort_key"],
            y_limits=self._last_plot_state["y_limits"],
            overlay_line=self._last_plot_state["overlay_line"],
            point_infos=self._last_plot_state["point_infos"],
        )

    def _handle_resize_redraw(self) -> None:
        self.figure.tight_layout()
        self._redraw_last_plot()

    def _schedule_resize_redraw(self) -> None:
        self._resize_debounce_timer.start(180)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._schedule_resize_redraw()


class CorrelationScatterChart(FigureCanvasQTAgg):
    def __init__(self, parent=None):  # type: ignore[override]
        self.figure = Figure(figsize=(7, 3))
        self.ax = self.figure.add_subplot(111)
        super().__init__(self.figure)
        self.setParent(parent)
        self.theme_mode: ThemeMode = "system"
        self._style_axes(dark=self._is_dark_mode())
        self._last_plot_state: dict[str, object] | None = None
        self._hover = _ScatterHoverController(self, self.ax)
        self._resize_debounce_timer = QTimer(self)
        self._resize_debounce_timer.setSingleShot(True)
        self._resize_debounce_timer.timeout.connect(self._handle_resize_redraw)

    def _is_dark_mode(self) -> bool:
        if self.theme_mode == "dark":
            return True
        if self.theme_mode == "light":
            return False
        if QGuiApplication.instance():
            return system_prefers_dark()
        palette = self.palette()
        window_color = palette.color(QPalette.ColorRole.Window)
        return window_color.lightness() < 128

    def set_theme_mode(self, mode: ThemeMode) -> None:
        self.theme_mode = mode
        self._style_axes(dark=self._is_dark_mode())
        self._redraw_last_plot()

    def set_open_point_callback(self, callback: Callable[[str], None] | None) -> None:
        self._hover.set_open_callback(callback)

    def _style_axes(self, x_label: str = "X", y_label: str = "Y", *, dark: bool) -> None:
        face = "#1f1f1f" if dark else "#f2f4f8"
        text = "#e6e6e6" if dark else "#1D2835"
        grid = "#555555" if dark else "#b8c5d3"
        border = "#9fb4c9" if dark else "#556075"
        self.figure.set_facecolor(face)
        self.ax.set_facecolor(face)
        self.ax.tick_params(axis="x", colors=text)
        self.ax.tick_params(axis="y", colors=text)
        for spine in self.ax.spines.values():
            spine.set_visible(True)
            spine.set_color(border)
            spine.set_linewidth(1.0)
        self.ax.set_xlabel(x_label, color=text)
        self.ax.set_ylabel(y_label, color=text)
        self.ax.grid(color=grid, linestyle=":", linewidth=0.7)

    def plot(
        self,
        points: List[tuple[float, float, str]],
        *,
        x_label: str,
        y_label: str,
        level_order: Optional[List[str]] = None,
        color_by_level: bool = True,
        show_regression: bool = True,
        show_legend: bool = True,
        stats_text: str = "",
        x_limits: Optional[tuple[float, float]] = None,
        y_limits: Optional[tuple[float, float]] = None,
        point_infos: Optional[List[ScatterPointInfo]] = None,
    ) -> None:
        self._last_plot_state = {
            "points": points,
            "x_label": x_label,
            "y_label": y_label,
            "level_order": level_order,
            "color_by_level": color_by_level,
            "show_regression": show_regression,
            "show_legend": show_legend,
            "stats_text": stats_text,
            "x_limits": x_limits,
            "y_limits": y_limits,
            "point_infos": point_infos,
        }
        self._hover.reset()
        self.ax.clear()
        dark = self._is_dark_mode()
        self._style_axes(x_label=x_label, y_label=y_label, dark=dark)
        if not points:
            self._hover.set_points([])
            self._draw_stats_text(stats_text, dark=dark)
            self._apply_layout()
            self.draw()
            return

        marker_color = "#7CC7FF" if dark else "#2F7ACC"
        if color_by_level:
            ordered_levels = level_order or sorted({level for _, _, level in points})
            color_map = cm.get_cmap("tab20", max(len(ordered_levels), 1))
            for idx, level in enumerate(ordered_levels):
                grouped = [(x, y) for x, y, point_level in points if point_level == level]
                if not grouped:
                    continue
                xs = [x for x, _ in grouped]
                ys = [y for _, y in grouped]
                self.ax.scatter(xs, ys, color=color_map(idx), alpha=0.82, label=level)
            if show_legend and len(ordered_levels) <= 12:
                legend = self.ax.legend(facecolor="#2A2A2A" if dark else "#FFFFFF", framealpha=0.85, loc="best")
                for text in legend.get_texts():
                    text.set_color("#E6E6E6" if dark else "#1D2835")
        else:
            xs = [x for x, _, _ in points]
            ys = [y for _, y, _ in points]
            self.ax.scatter(xs, ys, c=marker_color, alpha=0.82)

        infos = _normalized_point_infos(points, point_infos)
        self._hover.set_points(
            [
                _HoverPoint(float(x), float(y), info)
                for (x, y, _level), info in zip(points, infos)
                if info is not None
            ]
        )

        xs = np.array([x for x, _, _ in points], dtype=float)
        ys = np.array([y for _, y, _ in points], dtype=float)
        if show_regression and len(points) >= 2 and float(np.ptp(xs)) > 0:
            slope, intercept = np.polyfit(xs, ys, 1)
            x_min = float(xs.min())
            x_max = float(xs.max())
            line_x = np.array([x_min, x_max], dtype=float)
            line_y = slope * line_x + intercept
            self.ax.plot(line_x, line_y, color="#F0B35A" if dark else "#B85C00", linewidth=1.4)
        if x_limits:
            self.ax.set_xlim(*x_limits)
        if y_limits:
            self.ax.set_ylim(*y_limits)
        self._draw_stats_text(stats_text, dark=dark)
        self._apply_layout()
        self.draw()

    def _redraw_last_plot(self) -> None:
        if not self._last_plot_state:
            self.draw_idle()
            return
        self.plot(
            self._last_plot_state["points"],
            x_label=self._last_plot_state["x_label"],
            y_label=self._last_plot_state["y_label"],
            level_order=self._last_plot_state["level_order"],
            color_by_level=self._last_plot_state["color_by_level"],
            show_regression=self._last_plot_state["show_regression"],
            show_legend=self._last_plot_state["show_legend"],
            stats_text=self._last_plot_state["stats_text"],
            x_limits=self._last_plot_state["x_limits"],
            y_limits=self._last_plot_state["y_limits"],
            point_infos=self._last_plot_state["point_infos"],
        )

    def _draw_stats_text(self, stats_text: str, *, dark: bool) -> None:
        if not stats_text:
            return
        self.ax.text(
            0.99,
            0.02,
            stats_text,
            transform=self.ax.transAxes,
            ha="right",
            va="bottom",
            fontsize=9,
            color="#E6E6E6" if dark else "#1D2835",
            bbox={
                "boxstyle": "round,pad=0.28",
                "facecolor": "#1f1f1f" if dark else "#FFFFFF",
                "edgecolor": "#666666" if dark else "#C8D1DC",
                "alpha": 0.82,
            },
            zorder=6,
        )

    def _apply_layout(self) -> None:
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "error",
                    message=r"Tight layout not applied.*",
                    category=UserWarning,
                )
                self.figure.tight_layout(pad=1.1)
        except UserWarning:
            self.figure.subplots_adjust(left=0.12, right=0.98, bottom=0.18, top=0.94)

    def _handle_resize_redraw(self) -> None:
        self._redraw_last_plot()

    def _schedule_resize_redraw(self) -> None:
        self._resize_debounce_timer.start(180)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._schedule_resize_redraw()


__all__ = [
    "StackedDensityChart",
    "BoxPlotCanvas",
    "DifficultyScatterChart",
    "CorrelationScatterChart",
    "ScatterPointInfo",
]
