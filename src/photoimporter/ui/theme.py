"""Light and dark appearance, and the few colours the app draws itself.

Most widgets take their colours from the application palette, which Qt switches between
light and dark. On Windows 11 the native "windows11" style does that by itself; elsewhere
(Windows 10, Linux) the app switches to the Fusion style with its own palettes.

Colours the app draws or styles itself come from `colors()`, which picks the light or dark
set to match the current palette. Widgets that use them restyle on a PaletteChange event.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from ..core.config import ACCENTS, DEFAULT_ACCENT


@dataclass(frozen=True)
class Colors:
    warning: str  # text that needs attention, e.g. photos outside the current view
    error: str  # e.g. an invalid date format
    separator: str  # lines, e.g. under day headers
    focus: str  # the dotted outline of the current tile
    tick_border: str  # an unticked day header
    placeholder_bg: str  # tiles still loading
    placeholder_text: str
    banner_bg: str  # the update bar
    banner_border: str
    disabled_bg: str  # the Import button with nothing to import
    disabled_text: str
    disabled_border: str


LIGHT = Colors(
    warning="#a15c00",
    error="#b00020",
    separator="#d0d0d0",
    focus="#888888",
    tick_border="#8a8a8a",
    placeholder_bg="#d8d8d8",
    placeholder_text="#777777",
    banner_bg="#e6f0fb",
    banner_border="#9cc1e8",
    disabled_bg="#d6dbe1",
    disabled_text="#8a929b",
    disabled_border="#c4cad1",
)

DARK = Colors(
    warning="#ffb74d",
    error="#ff6b81",
    separator="#4a4a4a",
    focus="#9a9a9a",
    tick_border="#9a9a9a",
    placeholder_bg="#3a3a3a",
    placeholder_text="#9a9a9a",
    banner_bg="#1f3347",
    banner_border="#35597d",
    disabled_bg="#3a3d41",
    disabled_text="#7d8389",
    disabled_border="#4a4e53",
)


_accent = QColor(ACCENTS[DEFAULT_ACCENT])
_system_accent: QColor | None = None  # Windows' accent colour, read before we change it


def accent() -> QColor:
    """The colour of selection borders, day-header ticks and the Import button."""
    return QColor(_accent)


def system_accent() -> QColor:
    """Windows' accent colour (Qt's default blue where there is none)."""
    if _system_accent is not None:
        return QColor(_system_accent)
    return QGuiApplication.palette().color(QPalette.ColorRole.Accent)


def accent_color(choice: str) -> QColor:
    return system_accent() if choice == "system" else QColor(ACCENTS.get(choice, "#1e88e5"))


def is_dark(palette: QPalette | None = None) -> bool:
    palette = palette or QGuiApplication.palette()
    return palette.color(QPalette.ColorRole.Window).lightness() < 128


def colors() -> Colors:
    return DARK if is_dark() else LIGHT


def muted(widget: QWidget) -> QWidget:
    """Show `widget`'s text in the palette's soft grey (hints, previews, counts)."""
    widget.setForegroundRole(QPalette.ColorRole.PlaceholderText)
    return widget


def dark_palette() -> QPalette:
    """A dark palette for the Fusion style, close to Windows 11's dark mode."""
    p = QPalette()
    roles = QPalette.ColorRole
    for role, color in (
        (roles.Window, "#202020"),
        (roles.WindowText, "#ffffff"),
        (roles.Base, "#2b2b2b"),
        (roles.AlternateBase, "#323232"),
        (roles.ToolTipBase, "#2b2b2b"),
        (roles.ToolTipText, "#ffffff"),
        (roles.Text, "#ffffff"),
        (roles.Button, "#2d2d2d"),
        (roles.ButtonText, "#ffffff"),
        (roles.BrightText, "#ff6b6b"),
        (roles.Light, "#3c3c3c"),
        (roles.Midlight, "#333333"),
        (roles.Mid, "#262626"),
        (roles.Dark, "#151515"),
        (roles.Shadow, "#000000"),
        (roles.Highlight, "#1e88e5"),
        (roles.HighlightedText, "#ffffff"),
        (roles.Link, "#64b5f6"),
        (roles.LinkVisited, "#ba68c8"),
        (roles.PlaceholderText, "#9a9a9a"),
    ):
        p.setColor(role, QColor(color))
    for role, color in (
        (roles.WindowText, "#7a7a7a"),
        (roles.Text, "#7a7a7a"),
        (roles.ButtonText, "#7a7a7a"),
        (roles.Button, "#262626"),
    ):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(color))
    return p


def _native_dark_mode(app: QApplication) -> bool:
    """Whether the style follows the colour scheme by itself (Windows 11's own style)."""
    return app.style().name().lower() == "windows11"


def apply_appearance(app: QApplication, mode: str, accent_choice: str = DEFAULT_ACCENT) -> None:
    """Switch the whole app to `mode` ("system", "light" or "dark") and an accent colour."""
    global _accent, _system_accent
    if _system_accent is None:
        _system_accent = QGuiApplication.palette().color(QPalette.ColorRole.Accent)
    schemes = {"light": Qt.ColorScheme.Light, "dark": Qt.ColorScheme.Dark}
    app.styleHints().setColorScheme(schemes.get(mode, Qt.ColorScheme.Unknown))
    if _native_dark_mode(app):
        palette = QPalette()  # only the accent roles; the style supplies the rest
    else:
        if mode == "system":
            dark = app.styleHints().colorScheme() == Qt.ColorScheme.Dark
        else:
            dark = mode == "dark"
        if app.style().name().lower() != "fusion" and dark:
            app.setStyle("Fusion")
        if app.style().name().lower() == "fusion":
            palette = dark_palette() if dark else app.style().standardPalette()
        else:
            palette = QPalette()
    _accent = accent_color(accent_choice)
    for role in (QPalette.ColorRole.Highlight, QPalette.ColorRole.Accent):
        palette.setColor(role, _accent)
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("white"))
    app.setPalette(palette)
