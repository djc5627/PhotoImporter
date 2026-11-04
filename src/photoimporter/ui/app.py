from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .. import __version__
from ..core.db import default_db_path
from .main_window import MainWindow

ICON = Path(__file__).with_name("icon.png")


def main() -> int:
    if sys.platform == "win32":
        # Show our icon on the taskbar instead of Python's.
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PhotoImporter.App")
    app = QApplication(sys.argv)
    app.setApplicationName("Photo Importer")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(QIcon(str(ICON)))
    window = MainWindow(default_db_path())
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
