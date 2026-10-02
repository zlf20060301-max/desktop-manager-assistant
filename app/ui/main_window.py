"""主窗口：扫描分类展示 + 搜索 + 归档 / 重命名 / 撤销 入口。"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from PySide6.QtCore import QModelIndex, QUrl, Qt
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..config import Config
from ..fileops import is_within, recycle, undo_batch
from ..journal import Journal
from ..scanner import Entry, category_counts, human_size, scan
from .archive_dialog import ArchiveDialog
from .file_model import FileTableModel, EntryFilterProxy
from .rename_dialog import RenameDialog
from .theme import QSS, category_icon


class MainWindow(QMainWindow):
    def __init__(self, cfg: Config, journal: Journal | None = None) -> None:
        super().__init__()
        self.cfg = cfg
        self.journal = journal if journal is not None else Journal()
        self.entries: list[Entry] = []

        self.setWindowTitle("桌面管家 — 桌面文档管理")
        self.resize(1280, 780)
        self.setMinimumSize(960, 600)

        self._build_ui()
        self._build_shortcuts()
        self.rescan()

    # ==================================================================
    # 界面搭建
    # ==================================================================

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 模型必须先于动作栏建立：动作栏的复选框要连到代理上
        self.model = FileTableModel([])
        self.proxy = EntryFilterProxy()
        self.proxy.setSourceModel(self.model)

        root.addWidget(self._build_header())
        root.addWidget(self._build_actionbar())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setContentsMargins(12, 8, 12, 8)
        splitter.addWidget(self._build_sidebar())

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(6)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(28)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2, 3, 4):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(5, 320)
        self.table.doubleClicked.connect(lambda _i: self.open_selected())
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.selectionModel().selectionChanged.connect(self._update_status)
        rl.addWidget(self.table, 1)

        self.empty_hint = QLabel("")
        self.empty_hint.setObjectName("Hint")
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rl.addWidget(self.empty_hint)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([240, 1040])
        root.addWidget(splitter, 1)

        self.status = self.statusBar()
        self.lbl_stats = QLabel("")
        self.lbl_sel = QLabel("")
        self.status.addWidget(self.lbl_stats, 1)
        self.status.addPermanentWidget(self.lbl_sel)

    # ------------------------------------------------------------------

    def _build_header(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("HeaderBar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(16, 12, 16, 12)
        h.setSpacing(12)

        title = QLabel("🗂️ 桌面管家")
        title.setObjectName("AppTitle")
        h.addWidget(title)

        self.lbl_path = QLabel("")
        self.lbl_path.setObjectName("AppPath")
        h.addWidget(self.lbl_path, 1)

        btn_choose = QPushButton("切换目录")
        btn_choose.clicked.connect(self.choose_directory)
        h.addWidget(btn_choose)

        btn_scan = QPushButton("重新扫描")
        btn_scan.setObjectName("Primary")
        btn_scan.clicked.connect(self.rescan)
        h.addWidget(btn_scan)
        return bar

    def _build_actionbar(self) -> QWidget:
        bar = QWidget()
        h = QHBoxLayout(bar)
        h.setContentsMargins(16, 8, 16, 0)
        h.setSpacing(8)

        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索文件名 / 分类 / 路径…（Ctrl+F）")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda t: self.proxy.set_keyword(t))
        self.search.setMinimumWidth(280)
        h.addWidget(self.search)

        self.chk_files = QCheckBox("只看文件")
        self.chk_files.toggled.connect(self.proxy.set_files_only)
        h.addWidget(self.chk_files)

        self.chk_hidden = QCheckBox("显示隐藏项")
        self.chk_hidden.setChecked(self.cfg.show_hidden)
        self.chk_hidden.toggled.connect(self._on_hidden_toggled)
        h.addWidget(self.chk_hidden)

        h.addStretch(1)

        self.btn_archive = QPushButton("自动归档")
        self.btn_archive.clicked.connect(self.open_archive_dialog)
        h.addWidget(self.btn_archive)

        self.btn_rename = QPushButton("批量重命名")
        self.btn_rename.clicked.connect(self.open_rename_dialog)
        h.addWidget(self.btn_rename)

        self.btn_undo = QPushButton("撤销上一步")
        self.btn_undo.clicked.connect(self.undo_last)
        h.addWidget(self.btn_undo)

        self.btn_delete = QPushButton("移入回收站")
        self.btn_delete.setObjectName("Danger")
        self.btn_delete.clicked.connect(self.delete_selected)
        h.addWidget(self.btn_delete)
        return bar

    def _build_sidebar(self) -> QWidget:
        self.cat_list = QListWidget()
        self.cat_list.setObjectName("CategoryList")
        self.cat_list.setMinimumWidth(190)
        self.cat_list.setMaximumWidth(300)
        self.cat_list.currentItemChanged.connect(self._on_category_changed)
        return self.cat_list

    def _build_shortcuts(self) -> None:
        def add(seq: str, slot) -> None:
            act = QAction(self)
            act.setShortcut(QKeySequence(seq))
            act.triggered.connect(slot)
            self.addAction(act)

        add("F5", self.rescan)
        add("Ctrl+F", lambda: (self.search.setFocus(), self.search.selectAll()))
        add("Ctrl+Z", self.undo_last)
        add("Ctrl+A", self._select_all)
        add("Delete", self.delete_selected)
        add("F2", self.open_rename_dialog)
        add("Return", self.open_selected)

    # ==================================================================
    # 数据
    # ==================================================================

    def rescan(self) -> None:
        root = Path(self.cfg.desktop_dir)
        if not root.is_dir():
            QMessageBox.warning(self, "目录无效", f"桌面目录不存在：\n{root}")
            return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.entries = scan(
                root,
                recursive=self.cfg.recursive,
                show_hidden=self.cfg.show_hidden,
                include_dirs=True,
            )
        finally:
            QApplication.restoreOverrideCursor()

        self.model.set_entries(self.entries)
        self.lbl_path.setText(f"当前目录：{root}")
        self._rebuild_categories()
        self._update_status()
        self.table.setFocus()

    def _rebuild_categories(self) -> None:
        counts = category_counts(self.entries)
        current = self._current_category()

        self.cat_list.blockSignals(True)
        self.cat_list.clear()

        total = len(self.entries)
        item = QListWidgetItem(f"📚  全部           {total}")
        item.setData(Qt.ItemDataRole.UserRole, None)
        self.cat_list.addItem(item)

        from ..categorizer import CATEGORY_ORDER

        for cat in CATEGORY_ORDER:
            n = counts.get(cat, 0)
            if n == 0:
                continue
            it = QListWidgetItem(f"{category_icon(cat)}  {cat}           {n}")
            it.setData(Qt.ItemDataRole.UserRole, cat)
            self.cat_list.addItem(it)

        # 恢复之前选中的分类
        target_row = 0
        for i in range(self.cat_list.count()):
            if self.cat_list.item(i).data(Qt.ItemDataRole.UserRole) == current:
                target_row = i
                break
        self.cat_list.setCurrentRow(target_row)
        self.cat_list.blockSignals(False)
        self.proxy.set_category(self._current_category())

    def _current_category(self) -> str | None:
        it = self.cat_list.currentItem()
        if it is None:
            return None
        return it.data(Qt.ItemDataRole.UserRole)

    def selected_entries(self) -> list[Entry]:
        rows = self.table.selectionModel().selectedRows()
        out: list[Entry] = []
        for proxy_idx in sorted(rows, key=lambda i: i.row()):
            src_idx = self.proxy.mapToSource(proxy_idx)
            e = self.model.entry_at(src_idx.row())
            if e is not None:
                out.append(e)
        return out

    def visible_entries(self) -> list[Entry]:
        out: list[Entry] = []
        for r in range(self.proxy.rowCount()):
            src_idx = self.proxy.mapToSource(self.proxy.index(r, 0))
            e = self.model.entry_at(src_idx.row())
            if e is not None:
                out.append(e)
        return out

    # ==================================================================
    # 槽函数
    # ==================================================================

    def _on_category_changed(self, *_args) -> None:
        self.proxy.set_category(self._current_category())
        self._update_status()

    def _on_hidden_toggled(self, flag: bool) -> None:
        self.cfg.show_hidden = bool(flag)
        self.cfg.save()
        self.rescan()

    def _select_all(self) -> None:
        self.table.selectAll()

    def _update_status(self, *_args) -> None:
        total = self.proxy.rowCount()
        all_count = len(self.entries)
        sel = len(self.selected_entries())
        size = sum(e.size for e in self.entries if not e.is_dir)
        text = f"共 {all_count} 项"
        if total != all_count:
            text += f"（当前筛选 {total} 项）"
        text += f" · 占用 {human_size(size)} · 目录 {self.cfg.desktop_dir}"
        self.lbl_stats.setText(text)
        self.lbl_sel.setText(f"已选中 {sel} 项" if sel else "")
        self.empty_hint.setText("没有匹配的条目，试试清空搜索或切换分类。" if total == 0 else "")
        self.btn_undo.setEnabled(self.journal.last_undoable() is not None)
        has_sel = sel > 0
        self.btn_rename.setEnabled(has_sel)
        self.btn_delete.setEnabled(has_sel)

    def choose_directory(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "选择要管理的目录", self.cfg.desktop_dir
        )
        if chosen:
            self.cfg.desktop_dir = chosen
            self.cfg.save()
            self.rescan()

    # ------------------------------------------------------------------

    def open_selected(self) -> None:
        for e in self.selected_entries()[:5]:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(e.path)))

    def open_containing_folder(self) -> None:
        for e in self.selected_entries()[:5]:
            if e.is_dir:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(e.path)))
            else:
                subprocess.Popen(f'explorer /select,"{e.path}"')

    def copy_paths(self) -> None:
        paths = "\n".join(str(e.path) for e in self.selected_entries())
        if paths:
            QGuiApplication.clipboard().setText(paths)
            self.status.showMessage(f"已复制 {len(self.selected_entries())} 条路径", 3000)

    def copy_names(self) -> None:
        names = "\n".join(e.name for e in self.selected_entries())
        if names:
            QGuiApplication.clipboard().setText(names)
            self.status.showMessage("已复制文件名", 3000)

    # ------------------------------------------------------------------

    def open_archive_dialog(self) -> None:
        dlg = ArchiveDialog(self.cfg, self.entries, self.journal, self)
        dlg.exec()
        if dlg.executed:
            self.rescan()

    def open_rename_dialog(self) -> None:
        entries = self.selected_entries()
        if not entries:
            QMessageBox.information(self, "批量重命名", "请先在列表里选中要改名的条目。")
            return
        dlg = RenameDialog(entries, self.journal, self)
        dlg.exec()
        if dlg.executed:
            self.rescan()

    def delete_selected(self) -> None:
        entries = self.selected_entries()
        if not entries:
            return
        names = "\n".join(f"  {e.name}" for e in entries[:10])
        if len(entries) > 10:
            names += f"\n  …… 以及另外 {len(entries) - 10} 项"
        ok = QMessageBox.question(
            self,
            "移入回收站",
            f"确认把以下 {len(entries)} 项移入回收站？\n\n{names}\n\n"
            "可在 Windows 回收站中还原。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ok != QMessageBox.StandardButton.Yes:
            return

        outside = [e for e in entries if not is_within(Path(self.cfg.desktop_dir), e.path)]
        if outside:
            QMessageBox.warning(self, "已阻止", "选中的条目不在当前目录内，已中止。")
            return

        success, msg = recycle(e.path for e in entries)
        if success:
            self.status.showMessage(msg, 5000)
            self.rescan()
        else:
            QMessageBox.warning(self, "删除失败", msg)

    def undo_last(self) -> None:
        batch = self.journal.last_undoable()
        if batch is None:
            QMessageBox.information(self, "撤销", "没有可撤销的操作。")
            return
        when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(batch.created_at))
        action = {"archive": "自动归档", "rename": "批量重命名"}.get(batch.action, batch.action)
        ok = QMessageBox.question(
            self,
            "撤销操作",
            f"将撤销：{action}（{when}）\n共 {len(batch.moves)} 项\n\n{batch.note}\n\n是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if ok != QMessageBox.StandardButton.Yes:
            return
        res = undo_batch(
            self.journal, batch.id, cleanup_dirs=Path(self.cfg.desktop_dir)
        )
        msg = f"撤销完成：{res.summary()}"
        if res.errors:
            msg += "\n\n" + "\n".join(res.errors[:10])
        QMessageBox.information(self, "撤销结果", msg)
        self.rescan()

    def show_history(self) -> None:
        batches = self.journal.recent(20)
        if not batches:
            QMessageBox.information(self, "操作记录", "还没有任何操作记录。")
            return
        lines = []
        for b in batches:
            when = time.strftime("%m-%d %H:%M", time.localtime(b.created_at))
            action = {"archive": "归档", "rename": "重命名"}.get(b.action, b.action)
            flag = "（已撤销）" if b.undone else ""
            lines.append(f"{when}  {action}  {len(b.moves)} 项{flag}  {b.note}")
        QMessageBox.information(self, "最近操作记录", "\n".join(lines))

    # ------------------------------------------------------------------

    def _show_context_menu(self, pos) -> None:
        if not self.selected_entries():
            return
        menu = QMenu(self)
        menu.addAction("打开", self.open_selected)
        menu.addAction("打开所在位置", self.open_containing_folder)
        menu.addSeparator()
        menu.addAction("批量重命名…", self.open_rename_dialog)
        menu.addAction("复制完整路径", self.copy_paths)
        menu.addAction("复制文件名", self.copy_names)
        menu.addSeparator()
        menu.addAction("移入回收站", self.delete_selected)
        menu.exec(self.table.viewport().mapToGlobal(pos))


def apply_theme(app: QApplication) -> None:
    app.setStyleSheet(QSS)
