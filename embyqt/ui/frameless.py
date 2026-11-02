"""无边框窗口的缩放热区辅助。"""

from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget


class ResizeHandle(QWidget):
    """透明热区：按下后交给窗口管理器做原生缩放。"""

    def __init__(self, edges, cursor, parent: QWidget) -> None:
        super().__init__(parent)
        self._edges = edges
        self.setCursor(cursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None:
                handle.startSystemResize(self._edges)
            event.accept()
            return
        super().mousePressEvent(event)


def create_resize_handles(window: QWidget) -> List[ResizeHandle]:
    specs = [
        (Qt.Edge.LeftEdge, Qt.CursorShape.SizeHorCursor),
        (Qt.Edge.RightEdge, Qt.CursorShape.SizeHorCursor),
        (Qt.Edge.TopEdge, Qt.CursorShape.SizeVerCursor),
        (Qt.Edge.BottomEdge, Qt.CursorShape.SizeVerCursor),
        (Qt.Edge.LeftEdge | Qt.Edge.TopEdge, Qt.CursorShape.SizeFDiagCursor),
        (Qt.Edge.RightEdge | Qt.Edge.BottomEdge, Qt.CursorShape.SizeFDiagCursor),
        (Qt.Edge.RightEdge | Qt.Edge.TopEdge, Qt.CursorShape.SizeBDiagCursor),
        (Qt.Edge.LeftEdge | Qt.Edge.BottomEdge, Qt.CursorShape.SizeBDiagCursor),
    ]
    return [ResizeHandle(edges, cursor, window) for edges, cursor in specs]


def position_resize_handles(window: QWidget, handles: List[ResizeHandle]) -> None:
    if not handles:
        return
    width, height = window.width(), window.height()
    thickness, corner = 6, 14
    rects = [
        (0, corner, thickness, height - 2 * corner),
        (width - thickness, corner, thickness, height - 2 * corner),
        (corner, 0, width - 2 * corner, thickness),
        (corner, height - thickness, width - 2 * corner, thickness),
        (0, 0, corner, corner),
        (width - corner, height - corner, corner, corner),
        (width - corner, 0, corner, corner),
        (0, height - corner, corner, corner),
    ]
    for handle, (x, y, w, h) in zip(handles, rects):
        handle.setGeometry(x, y, w, h)
        handle.raise_()
