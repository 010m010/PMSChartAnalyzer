from __future__ import annotations

from typing import Callable, Dict, List, Optional

import matplotlib
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib import cm, rcParams
from matplotlib.widgets import SpanSelector
from PyQt6.QtGui import QPalette, QGuiApplication

from ..theme import system_prefers_dark

# Prefer Windows-installed Meiryo to avoid missing font warnings; fall back to common JP fonts.
rcParams["font.family"] = ["Meiryo", "Yu Gothic", "MS Gothic", "sans-serif"]

matplotlib.use("Agg")

ThemeMode = str  # "system", "light", "dark"

class StackedDensityChart(FigureCanvasQTAgg):
    def __init__(self, parent=None):  # type: ignore[override]
        self.figure = Figure(figsize=(8, 3))
        self.ax = self.figure.add_subplot(111)
        super().__init__(self.figure)
        self.setParent(parent)
        self.theme_mode: ThemeMode = "system"
        self._style_axes(dark=self._is_dark_mode())
        self._bars = None
        self._bar_colors: list[str] = []
        self._selection_callback: Optional[Callable[[float, float], None]] = None
        self._selection_artist = None
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
        self.draw()

    def _style_axes(self, *, dark: bool) -> None:
        face = "black" if dark else "white"
        text = "white" if dark else "black"
        grid = "#444" if dark else "#ccc"
        self.figure.set_facecolor(face)
        self.ax.set_facecolor(face)
        self.ax.tick_params(axis="x", colors=text)
        self.ax.tick_params(axis="y", colors=text)
        self.ax.spines["bottom"].set_color(text)
        self.ax.spines["left"].set_color(text)
        self.ax.spines["top"].set_visible(False)
        self.ax.spines["right"].set_visible(False)
        self.ax.set_xlabel("Seconds", color=text)
        self.ax.set_ylabel("Notes", color=text)
        self.ax.grid(color=grid, linestyle=":", linewidth=0.5)

    def plot(
        self,
        per_second_by_key: List[List[int]],
        title: str | None = None,
        *,
        total_time: float | None = None,
        terminal_window: float | None = None,
        y_max: float | None = None,
    ) -> None:
        self.ax.clear()
        self._clear_selection()
        dark = self._is_dark_mode()
        self._style_axes(dark=dark)
        if not per_second_by_key:
            self.draw()
            return
        self._bar_colors = []

        totals = [sum(row) for row in per_second_by_key]
        x = list(range(len(per_second_by_key)))
        colors = [self._color_for_density(val) for val in totals]
        self._bar_colors = colors
        self._bars = self.ax.bar(x, totals, color=colors, width=0.9)
        grid = "#444" if dark else "#ccc"
        self.ax.grid(color=grid, linestyle=":", linewidth=0.5)
        if title:
            self.ax.set_title(title, color="white" if dark else "black")
        else:
            self.ax.set_title("秒間密度", color="white" if dark else "black")
        if total_time and terminal_window:
            start = max(total_time - terminal_window, 0)
            start_bin = int(start)
            end_bin = len(per_second_by_key)
            face = "#888888" if dark else "#CCCCCC"
            start_edge = max(start_bin - 0.5, -0.5)
            end_edge = end_bin - 0.5
            self.ax.axvspan(start_edge, end_edge, color=face, alpha=0.2, zorder=0)
            self.ax.text(
                max(start_edge + 0.2, 0.0),
                self.ax.get_ylim()[1] * 0.9,
                "終端範囲",
                color="black" if not dark else "white",
                fontsize=9,
            )
        if y_max:
            self.ax.set_ylim(top=y_max)
        self.figure.tight_layout()
        self.draw()

    def _color_for_density(self, density: int) -> str:
        # Bucket every 10 density and map to a perceptually-uniform colormap
        bucket = min(density // 10, 9)
        cmap = cm.get_cmap("plasma", 10)
        r, g, b, _ = cmap(bucket)
        return f"#{int(r*255):02X}{int(g*255):02X}{int(b*255):02X}"

    def set_selection_callback(self, callback: Optional[Callable[[float, float], None]]) -> None:
        self._selection_callback = callback

    def clear_selection(self) -> None:
        self._clear_selection()

    def _on_span_select(self, x_min: float, x_max: float) -> None:
        if x_min is None or x_max is None:
            return
        start_raw, end_raw = sorted([x_min, x_max])
        start_bin = max(int(start_raw // 1), 0)
        end_bin = max(start_bin + 1, int((-(-end_raw // 1))))  # ceil for ints
        if self._bars:
            end_bin = min(end_bin, len(self._bars))
        self._draw_selection_region(start_bin, end_bin)
        if self._selection_callback:
            self._selection_callback(float(start_bin), float(end_bin))

    def _draw_selection_region(self, start_bin: int, end_bin: int) -> None:
        if self._selection_artist:
            try:
                self._selection_artist.remove()
            except ValueError:
                pass
        face = "#66CCFF" if not self._is_dark_mode() else "#2E8BC0"
        start_edge = start_bin - 0.5
        end_edge = end_bin - 0.5
        self._selection_artist = self.ax.axvspan(start_edge, end_edge, color=face, alpha=0.2, zorder=0)
        self._apply_bar_highlight(start_bin, end_bin)
        self.draw_idle()

    def _clear_selection(self) -> None:
        if self._selection_artist:
            try:
                self._selection_artist.remove()
            except ValueError:
                pass
            self._selection_artist = None
        if self._bars:
            for patch, color in zip(self._bars, self._bar_colors):
                patch.set_color(color)
        self.draw_idle()

    def _apply_bar_highlight(self, start_bin: int, end_bin: int) -> None:
        if not self._bars:
            return
        for idx, patch in enumerate(self._bars):
            if idx < len(self._bar_colors):
                base_color = self._bar_colors[idx]
            else:
                base_color = patch.get_facecolor()
            if start_bin <= idx < end_bin:
                patch.set_color("#3BA7FF")
            else:
                patch.set_color(base_color)


class BoxPlotCanvas(FigureCanvasQTAgg):
    def __init__(self, parent=None):  # type: ignore[override]
        self.figure = Figure(figsize=(6, 4))
        self.ax = self.figure.add_subplot(111)
        super().__init__(self.figure)
        self.setParent(parent)
        self.theme_mode: ThemeMode = "system"

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
        self.draw()

    def _style_axes(self, *, dark: bool) -> None:
        face = "black" if dark else "white"
        text = "white" if dark else "black"
        grid = "#444" if dark else "#ccc"
        self.figure.set_facecolor(face)
        self.ax.set_facecolor(face)
        self.ax.tick_params(axis="x", colors=text, rotation=45)
        self.ax.tick_params(axis="y", colors=text)
        for spine in ("bottom", "left"):
            self.ax.spines[spine].set_color(text)
        for spine in ("top", "right"):
            self.ax.spines[spine].set_visible(False)
        self.ax.set_title(self.ax.get_title(), color=text)
        self.ax.set_ylabel(self.ax.get_ylabel(), color=text)
        self.ax.grid(True, linestyle=":", linewidth=0.5, color=grid)

    def plot(self, values: Dict[str, List[float]], metric_name: str, *, y_limits: Optional[tuple[float, float]] = None) -> None:
        self.ax.clear()
        dark = self._is_dark_mode()
        if not values:
            self.draw()
            return

        labels = list(values.keys())
        data = [values[label] for label in labels]
        colors = {
            "edge": "#66CCFF" if dark else "#004A80",
            "fill": "#224466" if dark else "#B3D9FF",
            "median": "#FFCC66" if dark else "#CC6600",
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
        self.figure.tight_layout()
        self.draw()


class DifficultyScatterChart(FigureCanvasQTAgg):
    def __init__(self, parent=None):  # type: ignore[override]
        self.figure = Figure(figsize=(7, 3))
        self.ax = self.figure.add_subplot(111)
        super().__init__(self.figure)
        self.setParent(parent)
        self.theme_mode: ThemeMode = "system"
        self._style_axes(dark=self._is_dark_mode())

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
        self.draw()

    def _style_axes(self, y_label: str = "密度", *, dark: bool) -> None:
        face = "black" if dark else "white"
        text = "white" if dark else "black"
        grid = "#444" if dark else "#ccc"
        self.figure.set_facecolor(face)
        self.ax.set_facecolor(face)
        self.ax.tick_params(axis="x", colors=text, rotation=45)
        self.ax.tick_params(axis="y", colors=text)
        for spine in ("bottom", "left"):
            self.ax.spines[spine].set_color(text)
        for spine in ("top", "right"):
            self.ax.spines[spine].set_visible(False)
        self.ax.set_xlabel("難易度", color=text)
        self.ax.set_ylabel(y_label, color=text)
        self.ax.grid(color=grid, linestyle=":", linewidth=0.5)

    def plot(
        self,
        points: List[tuple[str, float]],
        *,
        y_label: str = "密度",
        order: Optional[List[str]] = None,
        sort_key: Optional[Callable[[str], object]] = None,
        y_limits: Optional[tuple[float, float]] = None,
    ) -> None:
        self.ax.clear()
        dark = self._is_dark_mode()
        self._style_axes(y_label=y_label, dark=dark)
        if not points:
            self.draw()
            return

        diffs = [p[0] for p in points]
        unique = order if order is not None else sorted({d for d in diffs}, key=sort_key or (lambda x: x))
        pos_map = {val: idx for idx, val in enumerate(unique)}
        filtered = [(d, den) for d, den in points if d in pos_map]
        x = [pos_map[d] for d, _ in filtered]
        y_vals = [den for _, den in filtered]
        marker_color = "#66CCFF" if dark else "#0066CC"
        self.ax.scatter(x, y_vals, c=marker_color, alpha=0.85)
        self.ax.set_xticks(list(pos_map.values()), labels=unique)
        grid = "#444" if dark else "#ccc"
        self.ax.grid(color=grid, linestyle=":", linewidth=0.5)
        if y_limits:
            self.ax.set_ylim(*y_limits)
        self.figure.tight_layout()
        self.draw()

    def _color_for_density(self, density: float) -> str:
        bucket = min(int(density // 10), 9)
        cmap = cm.get_cmap("plasma", 10)
        r, g, b, _ = cmap(bucket)
        return f"#{int(r*255):02X}{int(g*255):02X}{int(b*255):02X}"


__all__ = ["StackedDensityChart", "BoxPlotCanvas", "DifficultyScatterChart"]
