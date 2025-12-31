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


def apply_app_palette(app: QApplication, mode: str) -> bool:
    """
    Apply a light/dark/system palette to the whole application and return whether dark mode is active.
    """

    palette = QPalette()
    dark_mode = mode == "dark" or (mode == "system" and system_prefers_dark())
    if dark_mode:
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
    else:
        palette = app.style().standardPalette()
        # Ensure readable dark text on light backgrounds even after switching from dark mode
        dark_text = QColor(20, 28, 53)
        palette.setColor(QPalette.ColorRole.Window, QColor(248, 250, 253))
        palette.setColor(QPalette.ColorRole.Base, QColor(255, 255, 255))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(242, 246, 252))
        palette.setColor(QPalette.ColorRole.Button, QColor(236, 240, 245))
        palette.setColor(QPalette.ColorRole.Shadow, QColor(175, 185, 200))
        palette.setColor(QPalette.ColorRole.Mid, QColor(205, 213, 225))
        palette.setColor(QPalette.ColorRole.Dark, QColor(185, 195, 210))
        palette.setColor(QPalette.ColorRole.WindowText, dark_text)
        palette.setColor(QPalette.ColorRole.Text, dark_text)
        palette.setColor(QPalette.ColorRole.ButtonText, dark_text)
        palette.setColor(QPalette.ColorRole.ToolTipText, dark_text)
        palette.setColor(QPalette.ColorRole.Highlight, QColor(47, 122, 204))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(80, 80, 80, 180))
        palette.setColor(QPalette.ColorRole.Link, QColor(0, 90, 180))
        palette.setColor(QPalette.ColorRole.LinkVisited, QColor(120, 70, 200))

    app.setPalette(palette)
    app.setStyleSheet(build_widget_styles(dark_mode))
    return dark_mode

def build_widget_styles(dark: bool) -> str:
    border = "#6A6A6A" if dark else "#9AA5B5"
    text = "#E6E6E6" if dark else "#1D2835"
    base = "#2B2B2B" if dark else "#F5F7FA"
    hover = "#3A3A3A" if dark else "#E5ECF4"
    popup = "#1F1F1F" if dark else "#FFFFFF"
    disabled = "#9BA3AE" if dark else "#7A8395"
    highlight = "#4A9DDE" if dark else "#2F7ACC"
    table_border = "#3E4653" if dark else "#7D8CA3"
    arrow_color = "%23E6E6E6" if dark else "%231D2835"
    arrow_icon = (
        f"data:image/svg+xml;utf8,"
        f"<svg xmlns='http://www.w3.org/2000/svg' width='12' height='8' viewBox='0 0 12 8'>"
        f"<path fill='{arrow_color}' d='M1 1l5 6 5-6z'/></svg>"
    )

    return f"""
    QGroupBox {{
        border: 1px solid {border};
        border-radius: 4px;
        margin-top: 8px;
        padding: 8px 8px 6px 8px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 4px;
        color: {text};
    }}
    QComboBox, QPushButton, QLineEdit {{
        background-color: {base};
        color: {text};
        border: 1px solid {border};
        border-radius: 4px;
        padding: 4px 6px;
    }}
    QComboBox {{
        padding-right: 28px;
    }}
    QPushButton:disabled, QLineEdit:disabled, QComboBox:disabled {{
        color: {disabled};
    }}
    QComboBox::drop-down {{
        border-left: 1px solid {border};
        width: 18px;
        background-color: {base};
    }}
    QComboBox::down-arrow {{
        image: url("{arrow_icon}");
        width: 12px;
        height: 8px;
        margin-right: 6px;
    }}
    QComboBox::down-arrow:on {{
        top: 1px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {popup};
        color: {text};
        selection-background-color: {highlight};
        selection-color: #ffffff;
    }}
    QPushButton:hover, QComboBox:hover, QLineEdit:hover {{
        background-color: {hover};
    }}
    QPushButton:pressed {{
        background-color: {highlight};
        color: #ffffff;
    }}
    QMenu {{
        background-color: {popup};
        color: {text};
        border: 1px solid {border};
    }}
    QMenu::item:selected {{
        background-color: {highlight};
        color: #ffffff;
    }}
    QMenu::separator {{
        height: 1px;
        background: {border};
        margin: 4px 6px;
    }}
    QMenuBar {{
        background-color: {base};
        color: {text};
        padding: 4px 8px;
    }}
    QMenuBar::item {{
        padding: 6px 10px;
        margin: 0 4px;
        background: transparent;
        border-radius: 4px;
    }}
    QMenuBar::item:selected {{
        background: {hover};
        color: {text};
    }}
    QMenuBar::item:pressed {{
        background: {highlight};
        color: #ffffff;
    }}
    QTableWidget, QTableView {{
        background-color: {popup};
        alternate-background-color: {base};
        color: {text};
        gridline-color: {table_border};
        border: 1px solid {table_border};
        selection-background-color: {highlight};
        selection-color: #ffffff;
    }}
    QHeaderView::section {{
        background-color: {base};
        color: {text};
        border: 1px solid {table_border};
        padding: 4px;
    }}
    """


__all__ = ["apply_app_palette", "build_widget_styles", "system_prefers_dark"]
