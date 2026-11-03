"""无边框窗口的自绘标题栏。"""

from __future__ import annotations

import sys
from typing import Optional

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from . import theme
from .widgets import ElidedLabel


class WindowControlButton(QPushButton):
    """自绘窗口按钮，图形始终按按钮矩形几何居中。"""

    def __init__(self, role: str, platform: str, parent: Optional[QWidget] = None) -> None:
        super().__init__("", parent)
        self._role = role
        self._platform = platform
        self._restore = False
        self._hover = False
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_restore(self, restore: bool) -> None:
        self._restore = bool(restore)
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        cx, cy = self.width() / 2.0, self.height() / 2.0
        mac = self._platform == "mac"
        if mac:
            if not self._hover:
                return
            color = QColor(0, 0, 0, 150)
            pen = QPen(color, 1.1)
        else:
            if self._role == "close" and self._hover:
                color = QColor("#ffffff")
            elif self._hover:
                color = QColor(theme.TEXT)
            else:
                color = QColor(theme.TEXT_MUTED)
            pen = QPen(color, 1.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if self._role == "minimize":
            half = 2.6 if mac else 4.0
            painter.drawLine(QPointF(cx - half, cy), QPointF(cx + half, cy))
        elif self._role == "close":
            half = 3.0 if mac else 3.3
            painter.drawLine(QPointF(cx - half, cy - half), QPointF(cx + half, cy + half))
            painter.drawLine(QPointF(cx + half, cy - half), QPointF(cx - half, cy + half))
        elif self._role == "maximize":
            if mac:
                half = 3.0
                if self._restore:
                    back = QRectF(cx - half + 0.8, cy - half - 0.8, half * 2, half * 2)
                    front = QRectF(cx - half - 0.8, cy - half + 0.8, half * 2, half * 2)
                    back_path = QPainterPath()
                    back_path.addRect(back)
                    front_path = QPainterPath()
                    front_path.addRect(front)
                    back_pen = QPen(pen)
                    back_color = QColor(color)
                    back_color.setAlphaF(back_color.alphaF() * 0.45)
                    back_pen.setColor(back_color)
                    painter.setPen(back_pen)
                    painter.drawPath(back_path.subtracted(front_path))
                    painter.setPen(pen)
                    painter.drawRect(front)
                else:
                    painter.drawLine(QPointF(cx - half, cy), QPointF(cx + half, cy))
                    painter.drawLine(QPointF(cx, cy - half), QPointF(cx, cy + half))
            else:
                half = 3.4
                if self._restore:
                    # 后层在右上，前层在左下，与前层重叠的部分不画。
                    back = QRectF(cx - half + 1.0, cy - half - 1.0, half * 2, half * 2)
                    front = QRectF(cx - half - 1.0, cy - half + 1.0, half * 2, half * 2)
                    back_path = QPainterPath()
                    back_path.addRect(back)
                    front_path = QPainterPath()
                    front_path.addRect(front)
                    back_pen = QPen(pen)
                    back_color = QColor(color)
                    back_color.setAlphaF(back_color.alphaF() * 0.45)
                    back_pen.setColor(back_color)
                    painter.setPen(back_pen)
                    painter.drawPath(back_path.subtracted(front_path))
                    painter.setPen(pen)
                    painter.drawRect(front)
                else:
                    painter.drawRect(QRectF(cx - half, cy - half, half * 2, half * 2))


class TitleBar(QFrame):
    """可拖动、双击最大化的标题栏，右侧是窗口按钮。"""

    minimize_requested = Signal()
    maximize_requested = Signal()
    close_requested = Signal()

    def __init__(
        self,
        title: str = "",
        icon: Optional[QIcon] = None,
        *,
        show_minimize: bool = True,
        show_maximize: bool = True,
        show_close: bool = True,
        show_tooltips: bool = True,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("titleBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(42)
        self.setProperty("rounded", True)
        self._show_tooltips = show_tooltips
        self._press_pos: Optional[QPoint] = None
        self._platform = (
            "mac" if sys.platform == "darwin"
            else "linux" if sys.platform.startswith("linux")
            else "windows"
        )
        self.setProperty("platform", self._platform)
        self._centered_title = self._platform in ("mac", "linux")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 6, 0)
        layout.setSpacing(8)

        logo = None
        if icon is not None:
            logo = QLabel()
            logo.setObjectName("titleBarLogo")
            logo.setFixedSize(24, 24)
            logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            logo.setPixmap(icon.pixmap(18, 18))
            logo.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self.title_label = ElidedLabel(title)
        self.title_label.setObjectName("titleBarTitle")
        self.title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        if self._centered_title:
            self.title_label.setParent(self)
            self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            self.title_label.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )

        # 先创建按钮，再按平台决定顺序和位置
        self.minimize_button = self._button("最小化", "titleButton", "minimize")
        self.maximize_button = self._button("最大化", "titleButton", "maximize")
        self.close_button = self._button("关闭", "titleCloseButton", "close")

        if self._platform == "mac":
            # macOS 红黄绿交通灯在左侧，顺序：关闭、最小化、最大化
            layout.setContentsMargins(14, 0, 6, 0)
            for button in (self.close_button, self.minimize_button, self.maximize_button):
                button.setFixedSize(14, 14)
                layout.addWidget(button)
            layout.addSpacing(10)
            if logo is not None:
                layout.addWidget(logo)
            layout.addStretch(1)
        else:
            if logo is not None:
                layout.addWidget(logo)
            if self._platform == "windows":
                layout.addWidget(self.title_label, 1)
            else:
                layout.addStretch(1)
            for button in (self.minimize_button, self.maximize_button, self.close_button):
                if self._platform == "linux":
                    button.setFixedSize(28, 28)
                else:
                    button.setFixedSize(38, 28)
                layout.addWidget(button)

        self.minimize_button.clicked.connect(self.minimize_requested)
        self.maximize_button.clicked.connect(self.maximize_requested)
        self.close_button.clicked.connect(self.close_requested)

        self.minimize_button.setVisible(show_minimize)
        self.maximize_button.setVisible(show_maximize)
        self.close_button.setVisible(show_close)

    def _button(self, tooltip: str, object_name: str, role: str) -> QPushButton:
        button = WindowControlButton(role, self._platform, self)
        button.setObjectName(object_name)
        button.setProperty("platform", self._platform)
        button.setProperty("role", role)
        if self._show_tooltips:
            button.setToolTip(tooltip)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return button

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._centered_title:
            margin = min(120, max(0, self.width() // 4))
            self.title_label.setGeometry(
                margin, 0, max(1, self.width() - margin * 2), self.height()
            )
            self.title_label.raise_()

    # ---- 状态 -----------------------------------------------------------
    def set_title(self, title: str) -> None:
        self.title_label.setText(title)

    def set_rounded(self, rounded: bool) -> None:
        self.setProperty("rounded", rounded)
        style = self.style()
        style.unpolish(self)
        style.polish(self)

    def set_maximized(self, maximized: bool) -> None:
        self.maximize_button.set_restore(bool(maximized))
        if self._show_tooltips:
            self.maximize_button.setToolTip("还原" if maximized else "最大化")
        self.setProperty("maximized", bool(maximized))
        style = self.style()
        style.unpolish(self)
        style.polish(self)

    # ---- 拖动 / 双击 ----------------------------------------------------
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if (
            self._press_pos is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and (event.globalPosition().toPoint() - self._press_pos).manhattanLength() > 4
        ):
            self._press_pos = None
            handle = self.window().windowHandle()
            if handle is not None:
                handle.startSystemMove()
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.maximize_requested.emit()
        super().mouseDoubleClickEvent(event)
