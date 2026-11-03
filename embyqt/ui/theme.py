"""主题：深色 / 浅色两套调色板，统一使用蓝色强调色。"""

from __future__ import annotations

import os
from typing import Dict

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QToolTip
from PySide6.QtGui import QColor, QFont, QPalette

DARK: Dict[str, str] = {
    "bg": "#0e1116",
    "sidebar": "#12161e",
    "surface": "#171c26",
    "surface_hi": "#1f2531",
    "surface_hover": "#242c3a",
    "border": "#262e3d",
    "text": "#e9edf5",
    "text_muted": "#8d96a9",
    "accent": "#2f8cff",
    "accent_hover": "#55a4ff",
    "accent_dark": "#0b4a94",
    "accent_soft": "rgba(47, 140, 255, 0.18)",
    "nav_hover": "rgba(47, 140, 255, 0.12)",
    "on_accent": "#ffffff",
    "danger": "#e5554e",
    "gold": "#f0b429",
    "scroll": "#313a4c",
    "scroll_hover": "#43506a",
    "placeholder_1": "#232937",
    "placeholder_2": "#171b24",
    "placeholder_text": "#3a4253",
    "row_bg": "#161b25",
    "row_hover": "#1b2130",
    "row_border": "#2e394c",
    "overlay_bg": "#10141b",
    "sidebar_divider": "#252c3a",
    "nav_text": "#b7c0d2",
    "chip_text": "#c6cddd",
    "chip_border": "#262e3d",
    "white": "#ffffff",
}

LIGHT: Dict[str, str] = {
    "bg": "#dbe6f5",
    "sidebar": "#cfdeef",
    "surface": "#ffffff",
    "surface_hi": "#e8f0fb",
    "surface_hover": "#c4d6ea",
    "border": "#b6c8df",
    "text": "#182a42",
    "text_muted": "#526987",
    "accent": "#1f6feb",
    "accent_hover": "#2f8cff",
    "accent_dark": "#c7dfff",
    "accent_soft": "rgba(31, 111, 235, 0.14)",
    "nav_hover": "rgba(31, 111, 235, 0.13)",
    "on_accent": "#ffffff",
    "danger": "#c23b32",
    "gold": "#a06d00",
    "scroll": "#aebfd5",
    "scroll_hover": "#91a8c3",
    "placeholder_1": "#d9e5f4",
    "placeholder_2": "#cbd9ec",
    "placeholder_text": "#7d92ac",
    "row_bg": "#ffffff",
    "row_hover": "#e4edf9",
    "row_border": "#b6c8df",
    "overlay_bg": "#dbe6f5",
    "sidebar_divider": "#b9cbe1",
    "nav_text": "#294563",
    "chip_text": "#294563",
    "chip_border": "#b6c8df",
    "white": "#ffffff",
}

SCHEME = "dark"
_P = dict(DARK)

# 兼容旧代码的模块级颜色常量（切换主题时会被重新赋值）
BG = SIDEBAR = SURFACE = SURFACE_HI = SURFACE_HOVER = BORDER = ""
TEXT = TEXT_MUTED = ACCENT = ACCENT_HOVER = ACCENT_DARK = DANGER = GOLD = ""
TEXT_COLOR = MUTED_COLOR = ACCENT_COLOR = QColor("#000000")
PLACEHOLDER_1 = PLACEHOLDER_2 = PLACEHOLDER_TEXT = ""
ROW_BG = ROW_HOVER = ROW_BORDER = OVERLAY_BG = ""
SCROLL = SCROLL_HOVER = SIDEBAR_DIVIDER = NAV_TEXT = CHIP_TEXT = CHIP_BORDER = ""
WHITE = ON_ACCENT = ""

FONT_STACK = '"Noto Sans CJK SC", "Source Han Sans SC", "Microsoft YaHei", "PingFang SC", "WenQuanYi Micro Hei", sans-serif'


def _apply_globals(p: Dict[str, str]) -> None:
    global BG, SIDEBAR, SURFACE, SURFACE_HI, SURFACE_HOVER, BORDER
    global TEXT, TEXT_MUTED, ACCENT, ACCENT_HOVER, ACCENT_DARK, DANGER, GOLD
    global TEXT_COLOR, MUTED_COLOR, ACCENT_COLOR
    global PLACEHOLDER_1, PLACEHOLDER_2, PLACEHOLDER_TEXT
    global ROW_BG, ROW_HOVER, ROW_BORDER, OVERLAY_BG
    global SCROLL, SCROLL_HOVER, SIDEBAR_DIVIDER, NAV_TEXT, CHIP_TEXT, CHIP_BORDER
    global WHITE, ON_ACCENT

    BG = p["bg"]
    SIDEBAR = p["sidebar"]
    SURFACE = p["surface"]
    SURFACE_HI = p["surface_hi"]
    SURFACE_HOVER = p["surface_hover"]
    BORDER = p["border"]
    TEXT = p["text"]
    TEXT_MUTED = p["text_muted"]
    ACCENT = p["accent"]
    ACCENT_HOVER = p["accent_hover"]
    ACCENT_DARK = p["accent_dark"]
    DANGER = p["danger"]
    GOLD = p["gold"]
    TEXT_COLOR = QColor(TEXT)
    MUTED_COLOR = QColor(TEXT_MUTED)
    ACCENT_COLOR = QColor(ACCENT)
    PLACEHOLDER_1 = p["placeholder_1"]
    PLACEHOLDER_2 = p["placeholder_2"]
    PLACEHOLDER_TEXT = p["placeholder_text"]
    ROW_BG = p["row_bg"]
    ROW_HOVER = p["row_hover"]
    ROW_BORDER = p["row_border"]
    OVERLAY_BG = p["overlay_bg"]
    SCROLL = p["scroll"]
    SCROLL_HOVER = p["scroll_hover"]
    SIDEBAR_DIVIDER = p["sidebar_divider"]
    NAV_TEXT = p["nav_text"]
    CHIP_TEXT = p["chip_text"]
    CHIP_BORDER = p["chip_border"]
    WHITE = p["white"]
    ON_ACCENT = p["on_accent"]


def build_stylesheet(p: Dict[str, str]) -> str:
    return f"""
* {{
    font-family: {FONT_STACK};
    outline: none;
}}
QWidget {{
    color: {p['text']};
    font-size: 13px;
}}
QMainWindow, QDialog {{
    background: {p['bg']};
}}
QMainWindow#mainWindow, QDialog#loginDialog {{
    background: transparent;
}}
QWidget#windowRoot {{
    background: transparent;
}}
QFrame#windowFrame {{
    background: {p['bg']};
    border: 1px solid {p['border']};
    border-radius: 16px;
}}
QFrame#windowFrame[maximized="true"] {{
    border-radius: 0;
    border: none;
}}
QFrame#loginFrame {{
    background: {p['bg']};
    border: 1px solid {p['border']};
    border-radius: 16px;
}}
QFrame#playerFrame {{
    background: {p['bg']};
    border: none;
    border-radius: 16px;
}}
QFrame#playerFrame[bordered="true"] {{
    border: 1px solid {p['border']};
}}
QFrame#playerFrame[flat="true"] {{
    background: #000000;
    border-radius: 0;
    border: none;
}}
QFrame#titleBar {{
    background: {p['sidebar']};
    border-top-left-radius: 16px;
    border-top-right-radius: 16px;
}}
QFrame#titleBar[maximized="true"],
QFrame#titleBar[rounded="false"] {{
    border-top-left-radius: 0;
    border-top-right-radius: 0;
}}
QLabel#titleBarTitle {{
    color: {p['text']};
    font-size: 13px;
    font-weight: 600;
}}
QPushButton#titleButton {{
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 2px 10px;
    color: {p['text_muted']};
    font-size: 14px;
}}
QPushButton#titleButton:hover {{
    background: {p['surface_hi']};
    color: {p['text']};
}}
QPushButton#titleCloseButton {{
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 2px 10px;
    color: {p['text_muted']};
    font-size: 14px;
}}
QPushButton#titleCloseButton:hover {{
    background: #e81123;
    color: #ffffff;
}}
/* Linux：圆形窗口按钮 */
QPushButton#titleButton[platform="linux"],
QPushButton#titleCloseButton[platform="linux"] {{
    background: {p['surface_hi']};
    border-radius: 14px;
    padding: 0;
    font-size: 15px;
}}
QPushButton#titleButton[platform="linux"]:hover {{
    background: {p['surface_hover']};
    color: {p['text']};
}}
QPushButton#titleCloseButton[platform="linux"]:hover {{
    background: #e81123;
    color: #ffffff;
}}
/* macOS：左侧红黄绿交通灯 */
QPushButton#titleButton[platform="mac"],
QPushButton#titleCloseButton[platform="mac"] {{
    border-radius: 7px;
    padding: 0;
    font-size: 10px;
    color: transparent;
}}
QPushButton#titleButton[platform="mac"][role="minimize"] {{
    background: #febc2e;
}}
QPushButton#titleButton[platform="mac"][role="maximize"] {{
    background: #28c840;
}}
QPushButton#titleCloseButton[platform="mac"] {{
    background: #ff5f57;
}}
QPushButton#titleButton[platform="mac"]:hover,
QPushButton#titleCloseButton[platform="mac"]:hover {{
    color: rgba(0, 0, 0, 0.58);
}}
QPushButton#titleButton[role="maximize"] {{
    font-size: 12px;
}}
QPushButton#titleButton[platform="mac"][role="maximize"] {{
    font-size: 9px;
}}
QLabel#windowStatus {{
    background: {p['sidebar']};
    color: {p['text_muted']};
    border-top: 1px solid {p['border']};
    border-bottom-left-radius: 16px;
    border-bottom-right-radius: 16px;
    padding: 2px 12px;
    font-size: 11px;
}}
QLabel#windowStatus[maximized="true"] {{
    border-bottom-left-radius: 0;
    border-bottom-right-radius: 0;
}}
/* ---- 侧边栏 ---- */
#sidebar {{
    background: {p['sidebar']};
    border-right: 1px solid {p['border']};
}}
#brandName {{
    font-size: 19px;
    font-weight: 700;
    color: {p['text']};
    letter-spacing: 0.5px;
}}
#brandSub {{
    font-size: 11px;
    color: {p['text_muted']};
}}
#sidebarSection {{
    color: {p['text_muted']};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1px;
    padding: 14px 14px 6px 14px;
}}
QPushButton#nav {{
    background: transparent;
    border: none;
    border-radius: 9px;
    text-align: left;
    padding: 9px 12px;
    color: {p['nav_text']};
    font-size: 13px;
}}
QPushButton#nav:hover {{
    background: {p['nav_hover']};
    color: {p['text']};
}}
QPushButton#nav:checked {{
    background: {p['accent_soft']};
    color: {p['text']};
    font-weight: 600;
}}
QPushButton#userMenuButton {{
    background: transparent;
    border: none;
    border-radius: 8px;
    text-align: left;
    padding: 2px;
}}
QPushButton#userMenuButton:hover {{
    background: {p['surface_hover']};
}}
QPushButton#userMenuItem {{
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 0;
}}
QLabel#userMenuText {{
    background: transparent;
    color: {p['text']};
    font-size: 13px;
}}
QPushButton#userMenuItem:hover {{
    background: {p['accent_soft']};
}}
#userName {{
    font-size: 13px;
    font-weight: 600;
}}
#userRole {{
    font-size: 11px;
    color: {p['text_muted']};
}}
QLabel#sidebarServer {{
    font-size: 11px;
    color: {p['text_muted']};
}}
QLabel#sidebarVersion {{
    font-size: 10px;
    color: {p['text_muted']};
    padding-top: 6px;
}}
QFrame#sidebarDivider {{
    background: {p['sidebar_divider']};
}}

/* ---- 按钮 ---- */
QPushButton {{
    background: {p['surface_hi']};
    border: 1px solid {p['border']};
    border-radius: 8px;
    padding: 8px 16px;
    color: {p['text']};
}}
QPushButton:hover {{
    background: {p['surface_hover']};
}}
QPushButton:pressed {{
    background: {p['surface']};
}}
QPushButton:disabled {{
    color: {p['text_muted']};
    background: {p['surface_hi']};
}}
QPushButton#primary {{
    background: {p['accent']};
    border: none;
    color: {p['on_accent']};
    font-weight: 700;
    padding: 10px 22px;
}}
QPushButton#primary:hover {{
    background: {p['accent_hover']};
}}
QPushButton#secondary {{
    background: rgba(255, 255, 255, 0.10);
    border: 1px solid rgba(255, 255, 255, 0.18);
    color: #ffffff;
    padding: 10px 20px;
}}
QPushButton#secondary:hover {{
    background: rgba(255, 255, 255, 0.18);
}}
QPushButton#link {{
    background: transparent;
    border: none;
    color: {p['text_muted']};
    padding: 4px 8px;
}}
QPushButton#link:hover {{
    color: {p['accent']};
}}
QToolTip {{
    background: {p['surface']};
    color: {p['text']};
    border: 1px solid {p['border']};
    border-radius: 6px;
    padding: 2px 6px;
    font-size: 10px;
}}
QPushButton#chip {{
    background: transparent;
    border: 1px solid {p['chip_border']};
    border-radius: 13px;
    padding: 5px 14px;
    color: {p['chip_text']};
}}
QPushButton#chip:hover {{
    border-color: {p['accent']};
    color: {p['text']};
}}
QPushButton#chip:checked {{
    background: {p['accent_soft']};
    border-color: {p['accent']};
    color: {p['text']};
}}
QPushButton#iconButton {{
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 4px 8px;
    color: #c3cad8;
}}
QPushButton#iconButton:hover {{
    background: rgba(255, 255, 255, 0.1);
    color: #ffffff;
}}
QPushButton#rowNav {{
    background: {p['surface_hi']};
    color: {p['text']};
    border: 1px solid {p['border']};
    border-radius: 22px;
    padding: 0;
}}
QPushButton#rowNav:hover {{
    background: {p['accent']};
    color: {p['on_accent']};
    border-color: {p['accent']};
}}
QPushButton#rowNav:disabled {{
    color: {p['text_muted']};
    background: {p['surface']};
    border-color: {p['border']};
}}

/* ---- 输入 ---- */
QLineEdit, QComboBox {{
    background: {p['surface']};
    border: 1px solid {p['border']};
    border-radius: 8px;
    padding: 9px 12px;
    color: {p['text']};
    selection-background-color: {p['accent_dark']};
}}
QLineEdit:focus, QComboBox:focus {{
    border-color: {p['accent']};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox QAbstractItemView {{
    background: {p['surface_hi']};
    border: 1px solid {p['border']};
    border-radius: 8px;
    padding: 4px;
    selection-background-color: {p['accent_dark']};
    color: {p['text']};
    outline: none;
}}
QComboBox QAbstractItemView::item {{
    min-height: 28px;
    padding: 4px 10px;
}}

/* ---- 滚动条 ---- */
QScrollArea {{
    background: transparent;
    border: none;
}}
QScrollArea > QWidget > QWidget {{
    background: transparent;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 5px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {p['scroll']};
    border-radius: 2px;
    min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{
    background: {p['scroll_hover']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 5px;
}}
QScrollBar::handle:horizontal {{
    background: {p['scroll']};
    border-radius: 2px;
    min-width: 32px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {p['scroll_hover']};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
}}

/* ---- 菜单 ---- */
QMenu {{
    background: {p['surface_hi']};
    border: 1px solid {p['border']};
    border-radius: 8px;
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 26px 7px 14px;
    border-radius: 6px;
}}
QMenu::item:selected {{
    background: {p['accent_soft']};
    color: {p['text']};
}}
QMenu::separator {{
    height: 1px;
    background: {p['border']};
    margin: 5px 8px;
}}

/* ---- 文本 ---- */
QLabel#pageTitle {{
    font-size: 24px;
    font-weight: 700;
    color: {p['text']};
}}
QLabel#sectionTitle {{
    font-size: 18px;
    font-weight: 700;
    color: {p['text']};
}}
QLabel#muted {{
    color: {p['text_muted']};
}}
QLabel#errorLabel {{
    color: {p['danger']};
    font-size: 12px;
}}
QLabel#metaChip {{
    background: rgba(128, 140, 160, 0.16);
    border-radius: 5px;
    padding: 2px 8px;
    color: {p['chip_text']};
    font-size: 12px;
}}
QFrame#card {{
    background: {p['surface']};
    border: 1px solid {p['border']};
    border-radius: 10px;
}}

/* ---- 各处的语义化文本颜色 ---- */
QLabel#posterTitle {{
    font-size: 13px;
    font-weight: 600;
    color: {p['text']};
}}
QLabel#posterTitle[hovered="true"] {{
    color: {p['accent']};
}}
QLabel#posterMeta {{
    font-size: 11px;
    color: {p['text_muted']};
}}
QLabel#personName {{
    font-size: 12px;
    color: {p['text']};
}}
QLabel#personRole {{
    font-size: 11px;
    color: {p['text_muted']};
}}
QLabel#episodeTitle {{
    font-size: 13px;
    font-weight: 600;
    color: {p['text']};
}}
QLabel#episodeOverview {{
    font-size: 11px;
    color: {p['text_muted']};
}}
QLabel#episodeInfo {{
    font-size: 11px;
    color: {p['text_muted']};
}}
QLabel#episodeThumb {{
    background: {p['surface_hi']};
    color: {p['text_muted']};
    font-size: 15px;
    font-weight: 700;
    border-radius: 6px;
}}
QLabel#fieldLabel {{
    font-size: 12px;
    color: {p['text_muted']};
    font-weight: 600;
}}
QLabel#loginTitle {{
    font-size: 24px;
    font-weight: 700;
    color: {p['text']};
}}
QLabel#loginSubtitle {{
    color: {p['text_muted']};
}}
QLabel#serverHint {{
    font-size: 11px;
    color: {p['text_muted']};
}}
QLabel#statusText {{
    font-size: 11px;
    color: {p['text_muted']};
}}
QLabel#settingsName {{
    font-size: 12px;
    color: {p['text_muted']};
}}
QLabel#settingsValue {{
    font-size: 13px;
    color: {p['text']};
}}
QLabel#settingsNote {{
    font-size: 12px;
    color: {p['text_muted']};
}}
QLabel#emptyHeading {{
    font-size: 16px;
    color: {p['text']};
}}
QStatusBar {{
    background: {p['sidebar']};
    color: {p['text_muted']};
    border-top: 1px solid {p['border']};
}}

/* ---- 播放器（始终深色） ---- */
QSlider::groove:horizontal {{
    height: 4px;
    background: {p['scroll']};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {p['accent']};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {p['text']};
    width: 12px;
    height: 12px;
    margin: -5px 0;
    border-radius: 6px;
}}
QSlider::handle:horizontal:hover {{
    background: {p['accent_hover']};
}}
QSlider::groove:vertical {{
    width: 4px;
    background: {p['scroll']};
    border-radius: 2px;
}}
QSlider::handle:vertical {{
    background: {p['text']};
    width: 12px;
    height: 12px;
    margin: 0 -5px;
    border-radius: 6px;
}}
"""


class _ThemeSignals(QObject):
    changed = Signal()


signals = _ThemeSignals()

STYLESHEET = ""
_apply_globals(DARK)
STYLESHEET = build_stylesheet(DARK)


def _palette_for(name: str):
    key = str(name).lower()
    if key == "light":
        return "light", LIGHT
    if key == "blue":  # 兼容旧配置：蓝色主题已合并进深色模式
        return "dark", DARK
    return "dark", DARK


def set_scheme(name: str) -> str:
    global SCHEME, STYLESHEET
    SCHEME, palette = _palette_for(name)
    _apply_globals(palette)
    STYLESHEET = build_stylesheet(palette)
    return SCHEME


def apply(app, name: str) -> str:
    scheme = set_scheme(name)
    app.setStyleSheet(STYLESHEET)
    _scheme, palette = _palette_for(scheme)
    tip_font = QFont(app.font())
    tip_font.setPixelSize(10)
    QToolTip.setFont(tip_font)
    tip_palette = QPalette()
    tip_palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(palette["surface"]))
    tip_palette.setColor(QPalette.ColorRole.ToolTipText, QColor(palette["text"]))
    tip_palette.setColor(QPalette.ColorRole.Window, QColor(palette["surface"]))
    tip_palette.setColor(QPalette.ColorRole.WindowText, QColor(palette["text"]))
    QToolTip.setPalette(tip_palette)
    for widget in app.allWidgets():
        widget.update()
    signals.changed.emit()
    return scheme


PREFERENCE = "system"
_PREFERENCE_CONNECTED = False


def system_scheme(app) -> str:
    """读取系统当前配色：优先 Qt 的 colorScheme，跨平台回退到调色板亮度。"""
    hints = app.styleHints()
    scheme = hints.colorScheme() if hints is not None else Qt.ColorScheme.Unknown
    if scheme == Qt.ColorScheme.Light:
        return "light"
    if scheme == Qt.ColorScheme.Dark:
        return "dark"
    color = app.palette().window().color()
    return "light" if color.lightness() > 128 else "dark"


def _connect_color_scheme(app) -> None:
    global _PREFERENCE_CONNECTED
    if _PREFERENCE_CONNECTED:
        return
    hints = app.styleHints()
    if hints is not None:
        hints.colorSchemeChanged.connect(lambda _value: _on_color_scheme_changed(app))
        _PREFERENCE_CONNECTED = True


def _on_color_scheme_changed(app) -> None:
    if PREFERENCE == "system":
        apply(app, system_scheme(app))


def apply_preference(app, mode: str = "system") -> str:
    """应用主题偏好：dark / light / system。"""
    global PREFERENCE
    value = str(mode or "").lower()
    if value == "blue":
        value = "dark"
    PREFERENCE = value if value in ("dark", "light", "system") else "system"
    scheme = system_scheme(app) if PREFERENCE == "system" else PREFERENCE
    apply(app, scheme)
    _connect_color_scheme(app)
    return scheme


def apply_system(app) -> str:
    """兼容旧入口：环境变量可临时覆盖偏好。"""
    hint = os.environ.get("EMBYQT_THEME", "").strip().lower()
    mode = "dark" if hint == "blue" else (hint if hint in ("dark", "light") else "system")
    return apply_preference(app, mode)
