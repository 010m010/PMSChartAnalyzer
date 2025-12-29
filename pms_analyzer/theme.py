from __future__ import annotations

from PyQt6.QtGui import QColor, QPalette, QGuiApplication
from PyQt6.QtWidgets import QApplication


def system_prefers_dark() -> bool:
    try:
        scheme = QGuiApplication.styleHints().colorScheme()  # type: ignore[attr-defined]
        return getattr(QPalette.ColorScheme, "Dark", None) == scheme
    except Exception:
        palette = QGuiApplication.palette()
        window_color = palette.color(QPalette.ColorRole.Window)
        return window_color.lightness() < 128


def apply_app_palette(app: QApplication, mode: str) -> None:
    """
    Apply a light/dark/system palette to the whole application.
    """

    palette = QPalette()
    if mode == "dark" or (mode == "system" and system_prefers_dark()):
        palette.setColor(QPalette.ColorRole.Window, QColor(30, 30, 30))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(220, 220, 220))
        palette.setColor(QPalette.ColorRole.Base, QColor(24, 24, 24))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(45, 45, 45))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(255, 255, 255))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor(0, 0, 0))
        palette.setColor(QPalette.ColorRole.Text, QColor(220, 220, 220))
        palette.setColor(QPalette.ColorRole.Button, QColor(45, 45, 45))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(220, 220, 220))
        palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(76, 163, 224))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(0, 0, 0))
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(200, 200, 200, 128))
        app.setPalette(palette)
    else:
        palette = app.style().standardPalette()
        # Ensure readable dark text on light backgrounds even after switching from dark mode
        dark_text = QColor(20, 20, 20)
        palette.setColor(QPalette.ColorRole.WindowText, dark_text)
        palette.setColor(QPalette.ColorRole.Text, dark_text)
        palette.setColor(QPalette.ColorRole.ButtonText, dark_text)
        palette.setColor(QPalette.ColorRole.ToolTipText, dark_text)
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(80, 80, 80, 180))
        app.setPalette(palette)


__all__ = ["apply_app_palette", "system_prefers_dark"]
