from __future__ import annotations

from typing import Dict, List

import matplotlib
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib import cm

matplotlib.use("Agg")


class StackedDensityChart(FigureCanvasQTAgg):
    def __init__(self, parent=None):  # type: ignore[override]
        self.figure = Figure(figsize=(8, 3), facecolor="black")
        self.ax = self.figure.add_subplot(111)
        super().__init__(self.figure)
        self.setParent(parent)
        self._style_axes()

    def _style_axes(self) -> None:
        self.ax.set_facecolor("black")
        self.ax.tick_params(axis="x", colors="white")
        self.ax.tick_params(axis="y", colors="white")
        self.ax.spines["bottom"].set_color("white")
        self.ax.spines["left"].set_color("white")
        self.ax.spines["top"].set_visible(False)
        self.ax.spines["right"].set_visible(False)
        self.ax.set_xlabel("Seconds", color="white")
        self.ax.set_ylabel("Notes", color="white")

    def plot(self, per_second_by_key: List[List[int]]) -> None:
        self.ax.clear()
        self._style_axes()
        if not per_second_by_key:
            self.draw()
            return

        totals = [sum(row) for row in per_second_by_key]
        max_val = max(totals) if totals else 0
        x = list(range(len(per_second_by_key)))
        colors = [self._color_for_density(val) for val in totals]
        self.ax.bar(x, totals, color=colors, width=0.9)
        self.ax.grid(color="#444", linestyle=":", linewidth=0.5)
        self.ax.set_title("秒間密度", color="white")
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

    def plot(self, values: Dict[str, List[float]], metric_name: str) -> None:
        self.ax.clear()
        if not values:
            self.draw()
            return

        labels = list(values.keys())
        data = [values[label] for label in labels]
        self.ax.boxplot(data, labels=labels, vert=True)
        self.ax.set_title(f"{metric_name} の分布")
        self.ax.set_ylabel(metric_name)
        self.ax.grid(True, linestyle=":", linewidth=0.5)
        self.figure.tight_layout()
        self.draw()


__all__ = ["StackedDensityChart", "BoxPlotCanvas"]
