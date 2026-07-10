"""MetaTaskGapFill — Application entry point."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from src.gui.evidence_colors import apply_theme_colors
from src.gui.main_window import MainWindow
from src.gui.theme import apply_theme
from src.utils.config import Config, ConfigError
from src.utils.constants import APP_NAME, APP_VERSION
from src.utils.logging_config import setup_logging


def main() -> None:
    setup_logging()
    try:
        config = Config.load()
    except ConfigError as exc:
        raise SystemExit(str(exc)) from exc

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)

    apply_theme(app)
    apply_theme_colors()

    window = MainWindow(config)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
