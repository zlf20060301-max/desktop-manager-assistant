"""桌面管家 —— 程序入口。

用法：
    .venv\\Scripts\\python.exe main.py
或双击项目根目录的「启动桌面管家.cmd」。
"""

from __future__ import annotations

import ctypes
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from app import APP_NAME, __version__  # noqa: E402
from app.config import DATA_DIR, Config  # noqa: E402
from app.ui.main_window import MainWindow, apply_theme  # noqa: E402

CRASH_LOG = DATA_DIR / "crash.log"


def _install_excepthook() -> None:
    """崩溃时写日志并弹窗，避免 pythonw 下无声退出。"""

    def hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            with CRASH_LOG.open("a", encoding="utf-8") as f:
                f.write(text + "\n" + "-" * 60 + "\n")
        except Exception:
            pass
        try:
            app = QApplication.instance()
            if app is not None:
                QMessageBox.critical(
                    None, "程序出错", f"发生未处理的异常，详情已写入：\n{CRASH_LOG}\n\n{text[-1500:]}"
                )
        except Exception:
            pass

    sys.excepthook = hook


def main() -> int:
    # 让任务栏正确显示应用图标而不是 python.exe
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            f"DeskManager.{__version__}"
        )
    except Exception:
        pass

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("DeskManager")
    apply_theme(app)
    _install_excepthook()

    cfg = Config.load()
    cfg.save()  # 首次运行落盘一份默认配置

    win = MainWindow(cfg)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
