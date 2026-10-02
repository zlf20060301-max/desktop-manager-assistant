"""主窗口：扫描分类展示 + 搜索 + 归档 / 重命名 / 撤销 入口。"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from PySide6.QtCore import QModelIndex, QTimer, QUrl, Qt
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

from ..config import DATA_DIR, Config
from ..content_index import ContentIndex, describe_status, index_path_for
from ..fileops import is_within, recycle, undo_batch
from ..journal import Journal
from ..scanner import Entry, category_counts, human_size, scan
from .archive_dialog import ArchiveDialog
from .file_model import (
    COL_CAT,
    COL_HIT,
    COL_NAME,
    COL_PATH,
    COL_SIZE,
    COL_TIME,
    COL_TYPE,
    EntryFilterProxy,
    FileTableModel,
)
from .indexer import IndexWorker
from .rename_dialog import RenameDialog
from .theme import QSS, category_icon

SEARCH_PLACEHOLDER = "搜索文件名 / 分类 / 路径…（Ctrl+F）"
SEARCH_PLACEHOLDER_CONTENT = "搜索文件名 / 分类 / 路径 / 文档正文…（Ctrl+F）"


class MainWindow(QMainWindow):
    def __init__(
        self,
        cfg: Config,
        journal: Journal | None = None,
        data_dir: Path | str | None = None,
    ) -> None:
        super().__init__()
        self.cfg = cfg
        self.journal = journal if journal is not None else Journal()
        # 内容索引库放哪。测试和多套环境可以指到别处，避免污染真实索引。
        self._data_dir = Path(data_dir) if data_dir is not None else DATA_DIR
        self.entries: list[Entry] = []

        # 内容搜索相关状态。索引库按需创建，不用内容搜索就不建库。
        self._index: ContentIndex | None = None
        self._indexer: IndexWorker | None = None
        self._hits: dict[str, tuple[str, int]] = {}

        self.setWindowTitle("桌面管家 — 桌面文档管理")
        self.resize(1360, 800)
        self.setMinimumSize(1000, 620)

        self._build_ui()
        self._build_shortcuts()
        self.rescan()

        # 恢复上次的内容搜索开关状态
        if self.cfg.content_search:
            self.chk_content.setChecked(True)

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
        hh.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        for c in (COL_CAT, COL_TYPE, COL_SIZE, COL_TIME):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(COL_HIT, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(COL_PATH, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(COL_PATH, 260)
        self.table.setColumnHidden(COL_HIT, True)   # 内容搜索开启后才显示
        self.table.doubleClicked.connect(lambda _i: self.open_selected())
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        rl.addWidget(self.table, 1)

        # 底部信息条：平时给空结果提示，内容搜索时显示命中上下文
        self.info_bar = QLabel("")
        self.info_bar.setObjectName("Hint")
        self.info_bar.setWordWrap(True)
        self.info_bar.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.info_bar.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.info_bar.setMinimumHeight(38)
        rl.addWidget(self.info_bar)

        # 搜索防抖：每敲一个字就查一遍数据库太浪费
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(180)
        self._search_timer.timeout.connect(self._run_content_search)

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
        self.search.setPlaceholderText(SEARCH_PLACEHOLDER)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._on_search_text)
        self.search.setMinimumWidth(280)
        h.addWidget(self.search)

        self.chk_content = QCheckBox("搜内容")
        self.chk_content.setToolTip(
            "在文档正文里搜索，而不只是文件名。\n"
            "支持 Word / Excel / PPT / PDF / txt / 代码等；\n"
            "首次开启会在后台建立索引，之后是增量的。"
        )
        self.chk_content.toggled.connect(self._on_content_toggled)
        h.addWidget(self.chk_content)

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
        self._update_info_bar()
        self.table.setFocus()

        # 开了内容搜索就把新增/改动过的文档补进索引
        if self.chk_content.isChecked():
            self.start_indexing()
            self._run_content_search()

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
        self._update_info_bar()

    def _on_hidden_toggled(self, flag: bool) -> None:
        self.cfg.show_hidden = bool(flag)
        self.cfg.save()
        self.rescan()

    def _on_selection_changed(self, *_args) -> None:
        self._update_status()
        self._update_info_bar()

    def _on_search_text(self, text: str) -> None:
        self.proxy.set_keyword(text)
        if self.chk_content.isChecked():
            self._search_timer.start()      # 防抖后再查内容
        else:
            self._update_status()
            self._update_info_bar()

    # ==================================================================
    # 内容搜索
    # ==================================================================

    def content_index(self) -> ContentIndex:
        """内容索引库。用不到内容搜索就不会创建这个文件。"""
        if self._index is None:
            self._index = ContentIndex(index_path_for(self._data_dir))
        return self._index

    def _on_content_toggled(self, flag: bool) -> None:
        self.cfg.content_search = bool(flag)
        self.cfg.save()

        self.proxy.set_content_mode(flag)
        self.table.setColumnHidden(COL_HIT, not flag)
        self.search.setPlaceholderText(
            SEARCH_PLACEHOLDER_CONTENT if flag else SEARCH_PLACEHOLDER
        )

        if flag:
            self.start_indexing()
            self._run_content_search()
        else:
            self._search_timer.stop()
            self._hits = {}
            self.model.set_hits({})
            self.proxy.set_hits({})
            self.status.clearMessage()
            self._update_status()
            self._update_info_bar()

    def start_indexing(self, *, force: bool = False) -> None:
        """在后台把新增/改动过的文档补进索引。"""
        if force:
            self.content_index().clear()
            self._hits = {}
            self.model.set_hits({})
            self.proxy.set_hits({})

        self._stop_indexing()
        worker = IndexWorker(self.content_index(), self.entries, self)
        worker.progress.connect(self._on_index_progress)
        worker.completed.connect(self._on_index_completed)
        self._indexer = worker
        worker.start()

    def _stop_indexing(self) -> None:
        worker, self._indexer = self._indexer, None
        if worker is not None and worker.isRunning():
            worker.cancel()
            worker.wait(5000)

    def _on_index_progress(self, done: int, total: int) -> None:
        if total:
            self.status.showMessage(f"正在提取文档正文… {done}/{total}", 0)

    def _on_index_completed(self, added: int, skipped: int, failed: int) -> None:
        worker, self._indexer = self._indexer, None
        if worker is not None:
            worker.wait(3000)        # 确认线程真的退出了再回收，避免 Qt 警告
            worker.deleteLater()
        self.status.clearMessage()
        if added or failed:
            self._run_content_search()   # 索引进度变了，重跑一次当前查询
        self._update_status()
        self._update_info_bar()

    def _run_content_search(self) -> None:
        query = self.search.text().strip()
        if not self.chk_content.isChecked() or not query:
            self._hits = {}
            self.model.set_hits({})
            self.proxy.set_hits({})
            self._update_status()
            self._update_info_bar()
            return

        try:
            self._hits = self.content_index().search(query)
        except Exception:  # noqa: BLE001 - 索引库出问题也不该让界面崩
            self._hits = {}
        self.model.set_hits(self._hits)
        self.proxy.set_hits(self._hits)
        self._update_status()
        self._update_info_bar()
        self._select_first_hit_if_none()

    def _select_first_hit_if_none(self) -> None:
        """筛完如果没选中任何行，自动选第一条，方便直接看命中上下文。"""
        if self.proxy.rowCount() and not self.table.selectionModel().selectedRows():
            self.table.selectRow(0)

    def rebuild_index(self) -> None:
        ok = QMessageBox.question(
            self,
            "重建内容索引",
            "将清空已提取的文档正文并重新索引当前目录。\n"
            "文件本身不会被改动，只是多花一点时间重新读取。\n\n是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ok != QMessageBox.StandardButton.Yes:
            return
        if not self.chk_content.isChecked():
            self.chk_content.setChecked(True)
        self.start_indexing(force=True)
        self.status.showMessage("正在重建内容索引…", 0)

    def _update_info_bar(self) -> None:
        chk = getattr(self, "chk_content", None)
        content_on = bool(chk and chk.isChecked())
        query = self.search.text().strip() if hasattr(self, "search") else ""
        total = self.proxy.rowCount() if hasattr(self, "proxy") else 0

        lines: list[str] = []
        if content_on and total == 0 and query:
            lines.append("没有找到包含该内容的文档。")
        elif not content_on and total == 0:
            lines.append("没有匹配的条目，试试清空搜索或切换分类。")

        selected = self.selected_entries() if hasattr(self, "table") else []
        if content_on and len(selected) == 1:
            e = selected[0]
            hit = self.model.hit_for(e)
            if hit:
                lines.append(f"命中 {hit[1]} 处　{hit[0]}")
            else:
                status, note = ("", "")
                if self._index is not None:
                    status, note = self._index.note_for(e.path)
                lines.append("未命中内容 · " + describe_status(status, note, e.ext))

        if hasattr(self, "info_bar"):
            self.info_bar.setText("\n".join(lines))

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
        if self.chk_content.isChecked() and self._hits:
            text += f" · 内容命中 {len(self._hits)} 个文档"
        text += f" · 占用 {human_size(size)} · 目录 {self.cfg.desktop_dir}"
        self.lbl_stats.setText(text)
        self.lbl_sel.setText(f"已选中 {sel} 项" if sel else "")
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
        if self.chk_content.isChecked():
            menu.addAction("重建内容索引…", self.rebuild_index)
        menu.addAction("移入回收站", self.delete_selected)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        """退出前停掉后台索引线程、关掉数据库，避免留下半截写入。"""
        self._search_timer.stop()
        self._stop_indexing()
        if self._index is not None:
            self._index.close()
            self._index = None
        super().closeEvent(event)


def apply_theme(app: QApplication) -> None:
    app.setStyleSheet(QSS)
