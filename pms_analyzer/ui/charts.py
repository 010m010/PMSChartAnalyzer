from __future__ import annotations

from typing import Callable, Dict, List, Optional

import matplotlib
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib import cm, rcParams
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

    def plot(self, per_second_by_key: List[List[int]], title: str | None = None) -> None:
        self.ax.clear()
        dark = self._is_dark_mode()
        self._style_axes(dark=dark)
        if not per_second_by_key:
            self.draw()
            return

        totals = [sum(row) for row in per_second_by_key]
        x = list(range(len(per_second_by_key)))
        colors = [self._color_for_density(val) for val in totals]
        self.ax.bar(x, totals, color=colors, width=0.9)
        grid = "#444" if dark else "#ccc"
        self.ax.grid(color=grid, linestyle=":", linewidth=0.5)
        if title:
            self.ax.set_title(title, color="white" if dark else "black")
        else:
            self.ax.set_title("秒間密度", color="white" if dark else "black")
        self.figure.tight_layout()
        self.draw()

    def _color_for_density(self, density: int) -> str:
        # Bucket every 10 density and map to a perceptually-uniform colormap
        bucket = min(density // 10, 9)
        cmap = cm.get_cmap("plasma", 10)
        r, g, b, _ = cmap(bucket)
        return f"#{int(r*255):02X}{int(g*255):02X}{int(b*255):02X}"


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
