# -*- coding: utf-8 -*-
"""Application entry point — sets up QApplication, palette, then shows MainWindow."""

import sys
from pathlib import Path

from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import QApplication, QStyle

from .constants import APP_NAME, APP_VENDOR
from .main_window import MainWindow


def _load_app_icon(app: QApplication) -> QIcon:
    """
    Use the bundled radar SVG when present; fall back to a stock Qt icon
    if the file is missing or fails to render (e.g. broken install).
    """
    svg_path = Path(__file__).resolve().parent / "icon.svg"
    if svg_path.is_file():
        icon = QIcon(str(svg_path))
        if not icon.isNull():
            return icon
    return app.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView)


def _build_palette() -> QPalette:
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window,          QColor("#0f1117"))
    pal.setColor(QPalette.ColorRole.WindowText,      QColor("#e2e8f0"))
    pal.setColor(QPalette.ColorRole.Base,            QColor("#0a0d14"))
    pal.setColor(QPalette.ColorRole.AlternateBase,   QColor("#0d1320"))
    pal.setColor(QPalette.ColorRole.Text,            QColor("#e2e8f0"))
    pal.setColor(QPalette.ColorRole.Button,          QColor("#1e293b"))
    pal.setColor(QPalette.ColorRole.ButtonText,      QColor("#e2e8f0"))
    pal.setColor(QPalette.ColorRole.Highlight,       QColor("#1d4ed8"))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    return pal


def main():
    app = QApplication.instance() or QApplication([])
    # Setting org/app names lets QStandardPaths resolve a per-app config dir.
    app.setOrganizationName(APP_VENDOR)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    app.setPalette(_build_palette())

    # Custom radar/binary icon — propagates to every top-level window.
    app.setWindowIcon(_load_app_icon(app))

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()