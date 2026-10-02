"""表格数据模型 + 搜索/分类过滤代理。"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor, QFont

from ..scanner import Entry, human_size
from .theme import category_icon

# 「命中内容」是内容搜索时才用到的列，关闭时会被隐藏
COL_NAME, COL_CAT, COL_TYPE, COL_SIZE, COL_TIME, COL_HIT, COL_PATH = range(7)
COLUMNS = ["名称", "分类", "类型", "大小", "修改时间", "命中内容", "位置"]

SORT_ROLE = Qt.ItemDataRole.UserRole + 1
ENTRY_ROLE = Qt.ItemDataRole.UserRole + 2


def path_key(p) -> str:
    return str(p).lower()


class FileTableModel(QAbstractTableModel):
    """把 Entry 列表映射成表格。"""

    def __init__(self, entries: list[Entry] | None = None, parent=None) -> None:
        super().__init__(parent)
        self._entries: list[Entry] = list(entries or [])
        self._hits: dict[str, tuple[str, int]] = {}

    # ---------- 数据源 ----------

    def set_entries(self, entries: list[Entry]) -> None:
        self.beginResetModel()
        self._entries = list(entries)
        self.endResetModel()

    def entries(self) -> list[Entry]:
        return list(self._entries)

    def entry_at(self, row: int) -> Entry | None:
        if 0 <= row < len(self._entries):
            return self._entries[row]
        return None

    # ---------- 内容搜索命中 ----------

    def set_hits(self, hits: dict[str, tuple[str, int]]) -> None:
        """设置 {路径小写: (命中片段, 命中次数)}，并刷新「命中内容」列。"""
        self._hits = dict(hits or {})
        if self._entries:
            top = self.index(0, COL_HIT)
            bottom = self.index(len(self._entries) - 1, COL_HIT)
            self.dataChanged.emit(top, bottom, [Qt.ItemDataRole.DisplayRole,
                                                Qt.ItemDataRole.ToolTipRole])

    def hit_for(self, entry: Entry) -> tuple[str, int] | None:
        return self._hits.get(path_key(entry.path))

    # ---------- Qt 接口 ----------

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._entries)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        e = self._entries[index.row()]
        col = index.column()

        if role == ENTRY_ROLE:
            return e

        if role == Qt.ItemDataRole.DisplayRole:
            if col == COL_NAME:
                return e.name
            if col == COL_CAT:
                return f"{category_icon(e.category)} {e.category}"
            if col == COL_TYPE:
                return e.suffix
            if col == COL_SIZE:
                return "—" if e.is_dir else human_size(e.size)
            if col == COL_TIME:
                return time.strftime("%Y-%m-%d %H:%M", time.localtime(e.mtime))
            if col == COL_HIT:
                hit = self._hits.get(path_key(e.path))
                return hit[0] if hit else ""
            if col == COL_PATH:
                return str(e.path)
            return None

        if role == SORT_ROLE:
            if col == COL_NAME:
                return e.name.lower()
            if col == COL_CAT:
                return e.category
            if col == COL_TYPE:
                return e.suffix
            if col == COL_SIZE:
                return -1 if e.is_dir else e.size
            if col == COL_TIME:
                return e.mtime
            if col == COL_HIT:
                hit = self._hits.get(path_key(e.path))
                return hit[1] if hit else 0
            if col == COL_PATH:
                return str(e.path).lower()
            return None

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (COL_SIZE, COL_TIME):
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if col in (COL_CAT, COL_TYPE):
                return int(Qt.AlignmentFlag.AlignCenter)
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        if role == Qt.ItemDataRole.ForegroundRole:
            if col == COL_HIT:
                return QColor("#b45309")       # 命中片段用暖色，和文件名区分开
            if e.is_dir:
                return QColor("#1d4ed8")
            if e.is_shortcut:
                return QColor("#6b7280")
            if e.hidden:
                return QColor("#9ca3af")
            return None

        if role == Qt.ItemDataRole.FontRole and e.is_dir and col != COL_HIT:
            f = QFont()
            f.setBold(True)
            return f

        if role == Qt.ItemDataRole.ToolTipRole:
            hit = self._hits.get(path_key(e.path))
            if col == COL_HIT and hit:
                return f"命中 {hit[1]} 处：\n{hit[0]}"
            kind = "文件夹" if e.is_dir else "文件"
            return (f"{kind}：{e.path}\n分类：{e.category}\n"
                    f"修改时间：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(e.mtime))}")

        return None


class EntryFilterProxy(QSortFilterProxyModel):
    """分类 + 关键词 + 类型 + 内容命中 过滤。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSortRole(SORT_ROLE)
        self.setDynamicSortFilter(True)
        self._category: str | None = None
        self._keyword = ""
        self._files_only = False
        self._content_mode = False
        self._hits: dict[str, tuple[str, int]] = {}

    def set_category(self, category: str | None) -> None:
        self._category = category or None
        self.invalidateFilter()

    def set_keyword(self, text: str) -> None:
        self._keyword = (text or "").strip().lower()
        self.invalidateFilter()

    def set_files_only(self, flag: bool) -> None:
        self._files_only = bool(flag)
        self.invalidateFilter()

    def set_content_mode(self, flag: bool) -> None:
        self._content_mode = bool(flag)
        self.invalidateFilter()

    def set_hits(self, hits: dict[str, tuple[str, int]]) -> None:
        self._hits = dict(hits or {})
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        model = self.sourceModel()
        if model is None:
            return True
        idx = model.index(source_row, 0, source_parent)
        e: Entry | None = model.data(idx, ENTRY_ROLE)
        if e is None:
            return False
        if self._files_only and e.is_dir:
            return False
        if self._category and e.category != self._category:
            return False

        if self._keyword:
            hay = f"{e.name} {e.category} {e.suffix} {e.path}".lower()
            name_hit = self._keyword in hay
            content_hit = self._content_mode and path_key(e.path) in self._hits
            if not (name_hit or content_hit):
                return False
        return True
