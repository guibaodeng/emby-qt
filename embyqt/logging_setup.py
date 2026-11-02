"""应用日志：可运行时开关、级别可配，输出到终端和轮转文件。"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

ROOT = "embyqt"
_FORMAT = "%(asctime)s %(levelname)-5s %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def log_file_path() -> str:
    """按平台选择可写的日志目录。"""
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Logs")
    else:
        base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "embyqt", "logs", "embyqt.log")


def configure(enabled: bool = True, level: str = "DEBUG") -> None:
    """重新配置根日志器；设置页修改后可立即生效。"""
    logger = logging.getLogger(ROOT)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:  # noqa: BLE001
            pass

    logger.propagate = False
    if not enabled:
        logger.disabled = True
        return

    logger.disabled = False
    level_value = str(level).upper()
    logger.setLevel(logging.DEBUG if level_value == "DEBUG" else logging.INFO)

    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)
    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(formatter)
    logger.addHandler(stream)

    path = log_file_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        file_handler = RotatingFileHandler(
            path, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError:
        path = ""

    logger.info(
        "日志已启用（级别 %s%s）",
        logging.getLevelName(logger.level),
        f"，文件 {path}" if path else "，仅终端",
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"{ROOT}.{name}" if name else ROOT)
