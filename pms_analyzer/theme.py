from __future__ import annotations

import sys

from PyQt6.QtGui import QColor, QPalette, QGuiApplication
from PyQt6.QtWidgets import QApplication


def system_prefers_dark() -> bool:
    try:
        scheme = QGuiApplication.styleHints().colorScheme()  # type: ignore[attr-defined]
        if getattr(QPalette.ColorScheme, "Dark", None) == scheme:
            return True
        if getattr(QPalette.ColorScheme, "Light", None) == scheme:
            return False
    except Exception:
        pass

    if sys.platform.startswith("win"):
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            ) as key:
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                return value == 0
        except Exception:
            # If Windows APIs are unavailable (e.g. Wine) fall back to palette detection
            pass

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
        palette.setColor(QPalette.ColorRole.WindowText, QColor(230, 230, 230))
        palette.setColor(QPalette.ColorRole.Base, QColor(24, 24, 24))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(50, 50, 50))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(245, 245, 245))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor(15, 15, 15))
        palette.setColor(QPalette.ColorRole.Text, QColor(230, 230, 230))
        palette.setColor(QPalette.ColorRole.Button, QColor(55, 55, 55))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(230, 230, 230))
        palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 140, 140))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(82, 170, 235))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(200, 200, 200, 180))
        palette.setColor(QPalette.ColorRole.Link, QColor(120, 190, 255))
        palette.setColor(QPalette.ColorRole.LinkVisited, QColor(190, 170, 255))
        palette.setColor(QPalette.ColorRole.Mid, QColor(70, 70, 70))
        palette.setColor(QPalette.ColorRole.Dark, QColor(18, 18, 18))
        palette.setColor(QPalette.ColorRole.Shadow, QColor(10, 10, 10))
        app.setPalette(palette)
    else:
        palette = app.style().standardPalette()
        # Ensure readable dark text on light backgrounds even after switching from dark mode
        dark_text = QColor(20, 20, 20)
        palette.setColor(QPalette.ColorRole.WindowText, dark_text)
        palette.setColor(QPalette.ColorRole.Text, dark_text)
        palette.setColor(QPalette.ColorRole.ButtonText, dark_text)
        palette.setColor(QPalette.ColorRole.ToolTipText, dark_text)
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(80, 80, 80, 180))
        palette.setColor(QPalette.ColorRole.Link, QColor(0, 90, 180))
        palette.setColor(QPalette.ColorRole.LinkVisited, QColor(120, 70, 200))
        app.setPalette(palette)


__all__ = ["apply_app_palette", "system_prefers_dark"]
