"""QSS stylesheet for the TRACE-GEM GUI.

All colors are defined in theme.py. This module just re-exports the
generated stylesheet for backward compatibility.
"""

from src.gui.theme import THEME, generate_stylesheet

MAIN_STYLESHEET = generate_stylesheet(THEME)
