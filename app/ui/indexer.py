"""内容索引的后台线程。

提取 PDF / Office 正文可能要几百毫秒到几秒，绝对不能放在 UI 线程里做，
否则搜索框会一卡一卡的。
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from ..content_index import ContentIndex


class IndexWorker(QThread):
    """把一批条目补进内容索引。"""

    progress = Signal(int, int)          # 已处理, 总数
    completed = Signal(int, int, int)    # 新索引, 跳过, 失败

    def __init__(self, index: ContentIndex, entries, parent=None) -> None:
        super().__init__(parent)
        self._index = index
        self._entries = list(entries)
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def run(self) -> None:  # noqa: D102 - QThread 入口
        try:
            added, skipped, failed = self._index.ensure(
                self._entries,
                progress=lambda done, total: self.progress.emit(done, total),
                should_cancel=lambda: self._cancelled,
            )
        except Exception:  # noqa: BLE001 - 后台线程里绝不能把异常抛出去
            self.completed.emit(0, 0, len(self._entries))
            return
        if not self._cancelled:
            self.completed.emit(added, skipped, failed)
