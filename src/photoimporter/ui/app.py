from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from ..core.db import default_db_path
from .main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Photo Importer")
    window = MainWindow(default_db_path())
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
