from __future__ import annotations

from typing import Dict, List

import matplotlib
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

matplotlib.use("Agg")


KEY_COLORS = [
    "#5DA5DA",
    "#FAA43A",
    "#60BD68",
    "#F17CB0",
    "#B2912F",
    "#B276B2",
    "#DECF3F",
    "#F15854",
    "#4D4D4D",
]


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

        x = list(range(len(per_second_by_key)))
        bottom = [0 for _ in x]
        for key_index in range(9):
            heights = [row[key_index] for row in per_second_by_key]
            self.ax.bar(
                x,
                heights,
                bottom=bottom,
                color=KEY_COLORS[key_index],
                width=0.9,
                label=f"Key {key_index + 1}",
            )
            bottom = [b + h for b, h in zip(bottom, heights)]

        self.ax.legend(facecolor="black", labelcolor="white", loc="upper right", fontsize="small")
        self.ax.grid(color="#444", linestyle=":", linewidth=0.5)
        self.figure.tight_layout()
        self.draw()


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


__all__ = ["StackedDensityChart", "BoxPlotCanvas", "KEY_COLORS"]
