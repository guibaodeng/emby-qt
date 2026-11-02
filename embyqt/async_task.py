"""把阻塞调用丢到线程池，回调回到 GUI 线程执行。"""

from __future__ import annotations

import os
import traceback
from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal

# 持有信号对象，避免 QRunnable 结束后信号对象被回收导致回调丢失
_LIVE: set = set()


class _Signals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class _Task(QRunnable):
    def __init__(self, fn: Callable[..., Any], args: tuple, kwargs: dict, signals: _Signals) -> None:
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:  # noqa: D401 - Qt 接口
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception as exc:  # noqa: BLE001 - 任何异常都应反馈到界面
            if os.environ.get("EMBYQT_DEBUG"):
                traceback.print_exc()
            self._emit(self.signals.failed, str(exc) or exc.__class__.__name__)
            return
        self._emit(self.signals.finished, result)

    @staticmethod
    def _emit(signal, payload) -> None:
        """退出过程中信号对象可能已被销毁，忽略即可。"""
        try:
            signal.emit(payload)
        except RuntimeError:
            pass


def run_async(
    fn: Callable[..., Any],
    *args: Any,
    on_done: Optional[Callable[[Any], None]] = None,
    on_error: Optional[Callable[[str], None]] = None,
    **kwargs: Any,
) -> None:
    signals = _Signals()
    _LIVE.add(signals)
    task = _Task(fn, args, kwargs, signals)

    def _cleanup(*_args: Any) -> None:
        _LIVE.discard(signals)

    if on_done is not None:
        signals.finished.connect(on_done, Qt.ConnectionType.QueuedConnection)
    if on_error is not None:
        signals.failed.connect(on_error, Qt.ConnectionType.QueuedConnection)
    signals.finished.connect(_cleanup, Qt.ConnectionType.QueuedConnection)
    signals.failed.connect(_cleanup, Qt.ConnectionType.QueuedConnection)
    QThreadPool.globalInstance().start(task)
