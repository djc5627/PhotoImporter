"""Light and dark appearance, and the few colours the app draws itself.

Most widgets take their colours from the application palette, which Qt switches between
light and dark. On Windows 11 the native "windows11" style does that by itself; elsewhere
(Windows 10, Linux) the app switches to the Fusion style with its own palettes.

Colours the app draws or styles itself come from `colors()`, which picks the light or dark
set to match the current palette. Widgets that use them restyle on a PaletteChange event.
"""

from __future__ import annotations

import tempfile
import weakref
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QGuiApplication,
    QIcon,
    QPainter,
    QPalette,
    QPixmap,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QWidget

from ..core.config import ACCENTS, DEFAULT_ACCENT


@dataclass(frozen=True)
class Colors:
    warning: str  # text that needs attention, e.g. photos outside the current view
    error: str  # e.g. an invalid date format
    separator: str  # lines, e.g. under day headers
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


def light_palette() -> QPalette:
    """A light palette for the Fusion style, on soft grey surfaces."""
    p = QPalette()
    roles = QPalette.ColorRole
    for role, color in (
        (roles.Window, "#f3f5f8"),
        (roles.WindowText, "#111827"),
        (roles.Base, "#ffffff"),
        (roles.AlternateBase, "#f6f8fb"),
        (roles.ToolTipBase, "#ffffff"),
        (roles.ToolTipText, "#111827"),
        (roles.Text, "#111827"),
        (roles.Button, "#f1f3f7"),
        (roles.ButtonText, "#111827"),
        (roles.BrightText, "#b00020"),
        (roles.Light, "#ffffff"),
        (roles.Midlight, "#eef0f4"),
        (roles.Mid, "#c9ced6"),
        (roles.Dark, "#9aa1ab"),
        (roles.Shadow, "#6b7280"),
        (roles.Link, "#1565c0"),
        (roles.LinkVisited, "#6a1b9a"),
        (roles.PlaceholderText, "#6b7280"),
    ):
        p.setColor(role, QColor(color))
    for role in (roles.WindowText, roles.Text, roles.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor("#a0a6ae"))
    return p


def mix(a: QColor | str, b: QColor | str, t: float) -> str:
    """`a` blended `t` (0 to 1) of the way towards `b`, as #rrggbb."""
    a, b = QColor(a), QColor(b)
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
    ).name()


@dataclass(frozen=True)
class Surfaces:
    """The layered greys of the modern look, tinted a little by the accent colour."""

    bg: str  # the window
    bg_glow: str  # the corner the background gradient starts from
    panel: str  # rounded panels on the background
    field: str  # buttons, text boxes and dropdowns
    field_hover: str
    line: str  # thin borders
    tile: str  # behind each thumbnail
    popup: str  # menus, dropdown lists and tooltips
    text: str
    muted: str
    disabled: str
    scroll: str


def surfaces(dark: bool, accent: QColor) -> Surfaces:
    if dark:
        bg = mix("#0b0d11", accent, 0.04)
        return Surfaces(
            bg=bg,
            bg_glow=mix("#0b0f14", accent, 0.26),
            panel=mix("#16181d", accent, 0.05),
            field=mix("#22252b", accent, 0.05),
            field_hover=mix("#2b2f36", accent, 0.08),
            line=mix("#2c3037", accent, 0.06),
            tile=mix("#1c1f24", accent, 0.04),
            popup=mix("#1d2026", accent, 0.05),
            text="#f2f4f7",
            muted="#9aa3ad",
            disabled="#6b727a",
            scroll=mix("#3a3f47", accent, 0.1),
        )
    return Surfaces(
        bg="#f3f5f8",
        bg_glow=mix("#f6f7fa", accent, 0.10),
        panel="#ffffff",
        field="#f1f3f7",
        field_hover="#e8ebf0",
        line="#e1e5eb",
        tile="#f6f7f9",
        popup="#ffffff",
        text="#111827",
        muted="#6b7280",
        disabled="#a0a6ae",
        scroll="#c9ced6",
    )


def current_surfaces() -> Surfaces:
    return surfaces(is_dark(), accent())


_ICON_SHAPES = {  # 24x24 line icons (from Lucide, ISC licence)
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
}
_icon_dir: Path | None = None


def icon_file(name: str, color: str, width: float = 2.5) -> str:
    """A small SVG icon in `color`, written once to a temporary folder, for stylesheets."""
    global _icon_dir
    if _icon_dir is None:
        _icon_dir = Path(tempfile.mkdtemp(prefix="photoimporter-icons-"))
    path = _icon_dir / f"{name}-{color.lstrip('#')}.svg"
    if not path.exists():
        path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"'
            f' fill="none" stroke="{color}" stroke-width="{width}" stroke-linecap="round"'
            f' stroke-linejoin="round">{_ICON_SHAPES[name]}</svg>'
        )
    return path.as_posix()


def switch_file(track: str, knob: str, position: str) -> str:
    """An on/off switch image (36x20) with the knob "left", "middle" or "right"."""
    global _icon_dir
    if _icon_dir is None:
        _icon_dir = Path(tempfile.mkdtemp(prefix="photoimporter-icons-"))
    path = _icon_dir / f"switch-{track.lstrip('#')}-{knob.lstrip('#')}-{position}.svg"
    if not path.exists():
        x = {"left": 10, "middle": 18, "right": 26}[position]
        path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="36" height="20" viewBox="0 0 36 20">'
            f'<rect x="0.5" y="0.5" width="35" height="19" rx="9.5" fill="{track}"/>'
            f'<circle cx="{x}" cy="10" r="7" fill="{knob}"/></svg>'
        )
    return path.as_posix()


def stylesheet(dark: bool, accent: QColor) -> str:
    """The app-wide style: rounded panels, fields and buttons on layered surfaces."""
    s = surfaces(dark, accent)
    a = accent.name()
    soft = mix(s.panel, accent, 0.18)
    return f"""
QMainWindow, QDialog {{ background: {s.bg}; }}
#central {{
  background: qradialgradient(cx:0, cy:0, radius:1.15, fx:0, fy:0,
                              stop:0 {s.bg_glow}, stop:0.6 {s.bg}, stop:1 {s.bg});
}}
QFrame#panel {{ background: {s.panel}; border: 1px solid {s.line}; border-radius: 16px; }}
QLabel#title {{ font-size: 19pt; font-weight: 700; }}
QLabel#emptyTitle {{ font-size: 14pt; font-weight: 600; padding-top: 6px; }}
QLabel#panelTitle {{ font-size: 13pt; font-weight: 600; padding: 2px 4px 6px 4px; }}
QLabel#section {{ color: {s.muted}; font-size: 8pt; font-weight: 600; letter-spacing: 1px;
  padding: 10px 4px 2px 4px; }}
QFrame#categoryRow {{ background: transparent; border: 1px solid transparent;
  border-radius: 12px; }}
QFrame#categoryRow:hover {{ background: {s.field}; }}
QFrame#categoryRow[active="true"] {{ background: {mix(s.panel, accent, 0.14)};
  border: 1px solid {mix(s.panel, accent, 0.55)}; }}
QLabel#chip {{ background: {s.field}; border-radius: 17px; }}
QLabel#rowNumber {{ font-size: 13pt; font-weight: 700; }}
QLabel#rowLabel {{ font-weight: 500; }}
QLabel#rowSub {{ font-size: 8.5pt; }}
QLabel#small {{ font-size: 8.5pt; }}
QCheckBox#switch::indicator {{ width: 36px; height: 20px; border: none; background: transparent;
  image: url({switch_file(s.line, s.muted, "left")}); }}
QCheckBox#switch::indicator:checked {{ image: url({switch_file(a, "#ffffff", "right")}); }}
QCheckBox#switch::indicator:indeterminate {{
  image: url({switch_file(mix(s.panel, accent, 0.6), "#ffffff", "middle")}); }}
QCheckBox#switch::indicator:disabled {{ image: url({switch_file(s.line, s.disabled, "left")}); }}
QFrame#segment {{ background: {s.field}; border: 1px solid {s.line}; border-radius: 10px; }}
QPushButton#segment {{ padding: 6px 0; border-radius: 8px; border: none; background: transparent;
  color: {s.muted}; font-weight: 500; min-height: 18px; }}
QPushButton#segment:hover {{ color: {s.text}; }}
QPushButton#segment:checked {{ background: {s.panel}; color: {s.text}; }}
QToolButton#roundButton {{ border-radius: 18px; padding: 0; min-width: 36px; max-width: 36px;
  min-height: 36px; max-height: 36px; }}
QToolButton#cardButton {{ border-radius: 18px; padding: 8px 30px 8px 14px; font-weight: 500; }}
QPushButton {{ min-height: 20px; }}
QLabel {{ background: transparent; }}
QPushButton, QToolButton {{
  background: {s.field}; color: {s.text}; border: 1px solid {s.line}; border-radius: 9px;
  padding: 6px 14px;
}}
QPushButton:hover, QToolButton:hover {{ background: {s.field_hover}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {s.line}; }}
QPushButton:disabled, QToolButton:disabled {{ color: {s.disabled}; }}
QPushButton:default {{ border: 1px solid {a}; }}
QToolButton::menu-indicator {{ image: url({icon_file("chevron-down", s.muted)}); width: 12px;
  height: 12px; subcontrol-origin: padding; subcontrol-position: right center; right: 10px; }}
QToolButton[popupMode="2"] {{ padding-right: 30px; }}
QLineEdit, QComboBox {{
  background: {s.field}; color: {s.text}; border: 1px solid {s.line}; border-radius: 9px;
  padding: 6px 10px; selection-background-color: {a}; selection-color: white;
}}
QLineEdit:focus, QComboBox:focus {{ border: 1px solid {a}; }}
QLineEdit:disabled, QComboBox:disabled {{ color: {s.disabled}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url({icon_file("chevron-down", s.muted)});
  width: 12px; height: 12px; }}
QComboBox::down-arrow:disabled {{ image: url({icon_file("chevron-down", s.disabled)}); }}
QRadioButton::indicator, QCheckBox::indicator {{ width: 14px; height: 14px; background: {s.field};
  border: 1.5px solid {s.muted}; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QRadioButton::indicator:checked {{ border: 4px solid {a}; background: white;
  width: 9px; height: 9px; }}
QCheckBox::indicator {{ border-radius: 4px; }}
QCheckBox::indicator:checked, QCheckBox::indicator:indeterminate {{
  background: {a}; border-color: {a};
  image: url({icon_file("check", "#ffffff", 3)}); }}
QRadioButton::indicator:disabled, QCheckBox::indicator:disabled {{ border-color: {s.disabled}; }}
QComboBox QAbstractItemView {{
  background: {s.popup}; color: {s.text}; border: 1px solid {s.line}; border-radius: 8px;
  padding: 4px; outline: none; selection-background-color: {soft}; selection-color: {s.text};
}}
QMenu {{ background: {s.popup}; color: {s.text}; border: 1px solid {s.line}; border-radius: 10px;
  padding: 6px; }}
QMenu::item {{ padding: 6px 14px; border-radius: 6px; }}
QMenu::item:selected {{ background: {soft}; }}
QMenu::separator {{ height: 1px; background: {s.line}; margin: 4px 8px; }}
QToolTip {{ background: {s.popup}; color: {s.text}; border: 1px solid {s.line}; padding: 5px 8px;
  border-radius: 6px; }}
QListWidget#thumbnails {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 6px 3px 6px 3px; }}
QScrollBar::handle:vertical {{ background: {s.scroll}; border-radius: 3px; min-height: 36px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
QSlider::groove:horizontal {{ height: 4px; background: {s.line}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
    stop:0 {mix(s.panel, accent, 0.4)}, stop:1 {a});
  border-radius: 2px;
}}
QSlider::handle:horizontal {{ background: {s.panel}; border: 3px solid {a};
  width: 10px; height: 10px; margin: -6px 0; border-radius: 8px; }}
QProgressBar {{ background: {s.field}; border: none; border-radius: 6px; min-height: 12px;
  max-height: 12px; color: transparent; }}
QProgressBar::chunk {{ background: {a}; border-radius: 6px; }}
QTabWidget::pane {{ background: {s.panel}; border: 1px solid {s.line}; border-radius: 12px;
  top: -1px; }}
QTabBar::tab {{ background: transparent; color: {s.muted}; padding: 8px 16px; margin-right: 4px;
  border: 1px solid transparent; border-top-left-radius: 10px; border-top-right-radius: 10px; }}
QTabBar::tab:selected {{ background: {s.panel}; color: {a}; border-color: {s.line};
  border-bottom-color: {s.panel}; font-weight: 600; }}
QTableWidget, QTreeWidget {{ background: {s.panel}; alternate-background-color: {s.tile};
  border: 1px solid {s.line}; border-radius: 10px; gridline-color: transparent;
  selection-background-color: {soft}; selection-color: {s.text}; outline: none; }}
QTableWidget::item, QTreeWidget::item {{ padding: 0 8px; border-bottom: 1px solid {s.line}; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: {s.field}; color: {s.muted}; border: none;
  border-bottom: 1px solid {s.line}; padding: 7px 8px; font-weight: 600; text-align: left; }}
QHeaderView::section:first {{ border-top-left-radius: 9px; }}
QHeaderView::section:last {{ border-top-right-radius: 9px; }}
QTableCornerButton::section {{ background: {s.field}; border: none; }}
"""


_ICONS = Path(__file__).parent / "icons"  # Lucide line icons (ISC licence)
_themed: list[tuple[weakref.ref, str, int]] = []  # widgets to re-colour on a theme change


def icon(name: str, size: int = 16, color: QColor | str | None = None) -> QIcon:
    """A bundled line icon drawn in `color` (default: the palette's text colour)."""
    color = QColor(color) if color else QGuiApplication.palette().color(QPalette.ColorRole.Text)
    svg = (_ICONS / f"{name}.svg").read_text().replace("currentColor", color.name())
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    result = QIcon()
    for scale in (1, 2):
        pixmap = QPixmap(size * scale, size * scale)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        pixmap.setDevicePixelRatio(scale)
        result.addPixmap(pixmap)
    return result


def set_icon(widget: QWidget, name: str, size: int = 16) -> None:
    """Give a button an icon that follows light and dark mode."""
    widget.setIcon(icon(name, size))
    widget.setIconSize(QSize(size, size))
    _themed.append((weakref.ref(widget), name, size))


def _recolour_icons() -> None:
    alive = []
    for ref, name, size in _themed:
        widget = ref()
        try:
            if widget is not None:
                widget.setIcon(icon(name, size))
                alive.append((ref, name, size))
        except RuntimeError:  # the Qt object is gone
            pass
    _themed[:] = alive


FONT_FAMILY = "Inter"
_fonts_loaded = False


def load_fonts() -> bool:
    """Make the bundled Inter font available; True if it is."""
    global _fonts_loaded
    if not _fonts_loaded:
        folder = Path(__file__).parent / "fonts"
        for path in sorted(folder.glob("*.otf")):
            QFontDatabase.addApplicationFont(str(path))
        _fonts_loaded = True
    return FONT_FAMILY in QFontDatabase.families()


def apply_appearance(app: QApplication, mode: str, accent_choice: str = DEFAULT_ACCENT) -> None:
    """Switch the whole app to `mode` ("system", "light" or "dark") and an accent colour.

    The app always uses the Fusion style with its own palettes and stylesheet, so it looks
    the same on every version of Windows.
    """
    global _accent, _system_accent
    if _system_accent is None:
        _system_accent = QGuiApplication.palette().color(QPalette.ColorRole.Accent)
    schemes = {"light": Qt.ColorScheme.Light, "dark": Qt.ColorScheme.Dark}
    app.styleHints().setColorScheme(schemes.get(mode, Qt.ColorScheme.Unknown))
    if mode == "system":
        dark = app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    else:
        dark = mode == "dark"
    if app.property("photoimporter_fusion") is not True:  # once: with a stylesheet set,
        app.setStyle("Fusion")  # style().name() no longer says "fusion"
        app.setProperty("photoimporter_fusion", True)
    if load_fonts():
        font = QFont(FONT_FAMILY)
        font.setPointSizeF(9.5)
        app.setFont(font)
    _accent = accent_color(accent_choice)
    palette = dark_palette() if dark else light_palette()
    for role in (QPalette.ColorRole.Highlight, QPalette.ColorRole.Accent):
        palette.setColor(role, _accent)
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("white"))
    app.setPalette(palette)
    app.setStyleSheet(stylesheet(dark, _accent))
    _recolour_icons()
