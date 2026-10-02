"""文件类型管理：查看/编辑分类与后缀，并能从本机软件扫描导入。

两块内容：
- ScanDialog  从注册表读到的本机文件类型，勾选后并入某个分类
- FileTypeDialog  分类与后缀的编辑主界面
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..categorizer import (
    CATEGORY_ORDER,
    EXT_TO_CATEGORY,
    PRO_CATEGORIES,
    CategoryMap,
    suggest_category,
)
from ..icons import CUSTOM_ICON_CHOICES, icon_for

# --------------------------------------------------------------------------
# 后台扫描
# --------------------------------------------------------------------------


class _ScanWorker(QThread):
    """读注册表可能慢到几秒，放到后台线程里做。"""

    done = Signal(list)

    def run(self) -> None:  # noqa: D102
        rows: list[tuple[str, str, str, str]] = []
        try:
            from .. import winfiletypes

            for item in winfiletypes.discover():
                cat = suggest_category(item.ext, item.type_name, item.app)
                rows.append((item.ext, item.display_name, item.app, cat))
        except Exception:  # noqa: BLE001 - 扫描失败就当成没扫到
            rows = []
        self.done.emit(rows)


# --------------------------------------------------------------------------
# 扫描结果对话框
# --------------------------------------------------------------------------


class ScanDialog(QDialog):
    """展示本机注册的文件类型，勾选后并入分类。"""

    def __init__(self, ext_map: dict[str, str], categories: list[str],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ext_map = ext_map
        self.categories = categories
        self.picked: list[tuple[str, str]] = []
        self._rows: list[tuple[str, str, str, str]] = []

        self.setWindowTitle("从本机软件扫描文件类型")
        self.resize(980, 700)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        self.lbl_status = QLabel("正在读取注册表，枚举本机已安装软件注册的文件类型…")
        self.lbl_status.setObjectName("SectionTitle")
        root.addWidget(self.lbl_status)

        hint = QLabel(
            "这些是 Windows 注册表里记录的文件类型，通常来自你装过的专业软件。"
            "<br>默认只勾选了「能猜出专业分类、且当前还没归到那个分类」的项，确认后加入。"
        )
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("显示："))
        self.filter_box = QComboBox()
        self.filter_box.addItem("有专业分类建议的", "pro")
        self.filter_box.addItem("全部", "all")
        self.filter_box.addItem("我还没归类的", "unknown")
        self.filter_box.currentIndexChanged.connect(self._refill)
        bar.addWidget(self.filter_box)
        bar.addStretch(1)
        self.btn_all = QPushButton("全选")
        self.btn_all.clicked.connect(lambda: self._set_all(True))
        bar.addWidget(self.btn_all)
        self.btn_none = QPushButton("全不选")
        self.btn_none.clicked.connect(lambda: self._set_all(False))
        bar.addWidget(self.btn_none)
        root.addLayout(bar)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["加入", "扩展名", "类型名", "关联程序", "归入分类"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 50)
        self.table.setColumnWidth(1, 120)
        self.table.setColumnWidth(3, 240)
        self.table.setColumnWidth(4, 150)
        root.addWidget(self.table, 1)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("加入选中的")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)

        self._worker = _ScanWorker(self)
        self._worker.done.connect(self._on_scanned)
        self._worker.start()

    # ------------------------------------------------------------------

    def _on_scanned(self, rows: list) -> None:
        self._rows = rows
        if not rows:
            self.lbl_status.setText("没有读到任何文件类型（可能不是 Windows 或注册表不可读）。")
        else:
            self.lbl_status.setText(f"共发现 {len(rows)} 种文件类型。")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(rows))
        self._refill()

    def _visible_rows(self) -> list[tuple[str, str, str, str]]:
        mode = self.filter_box.currentData()
        out = []
        for row in self._rows:
            ext, _name, _app, cat = row
            current = self.ext_map.get(ext, "")
            if mode == "pro":
                if cat in PRO_CATEGORIES and current != cat:
                    out.append(row)
            elif mode == "unknown":
                if not current:
                    out.append(row)
            else:
                out.append(row)
        return out

    def _refill(self) -> None:
        rows = self._visible_rows()
        self.table.setRowCount(len(rows))
        for r, (ext, name, app, cat) in enumerate(rows):
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            should = bool(cat) and self.ext_map.get(ext, "") != cat
            chk.setCheckState(Qt.CheckState.Checked if should else Qt.CheckState.Unchecked)
            self.table.setItem(r, 0, chk)

            for c, text in enumerate([ext, name or "—", app or "—"], start=1):
                it = QTableWidgetItem(text)
                if c == 3:
                    it.setToolTip(text)
                self.table.setItem(r, c, it)

            combo = QComboBox()
            combo.addItems(self.categories)
            combo.setCurrentText(cat if cat in self.categories else "其他")
            self.table.setCellWidget(r, 4, combo)

    def _set_all(self, flag: bool) -> None:
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if item is not None:
                item.setCheckState(Qt.CheckState.Checked if flag else Qt.CheckState.Unchecked)

    def _accept(self) -> None:
        self.picked = []
        for r in range(self.table.rowCount()):
            chk = self.table.item(r, 0)
            if chk is None or chk.checkState() != Qt.CheckState.Checked:
                continue
            ext = self.table.item(r, 1).text()
            combo = self.table.cellWidget(r, 4)
            cat = combo.currentText() if combo is not None else "其他"
            if ext:
                self.picked.append((ext, cat))
        self.accept()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._worker.isRunning():
            self._worker.wait(3000)
        super().closeEvent(event)


# --------------------------------------------------------------------------
# 主管理界面
# --------------------------------------------------------------------------


class FileTypeDialog(QDialog):
    """分类与后缀的编辑界面。保存时写回 config。"""

    def __init__(self, cfg, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.changed = False

        base = CategoryMap.from_config(cfg)
        self.custom: list[dict] = [{"name": n, "icon": i} for n, i in base.custom_categories()]
        self.ext_map: dict[str, str] = dict(base.effective_ext_map())
        # 把自定义分类里的后缀也并进来（effective_ext_map 已含用户覆盖）

        self.setWindowTitle("文件类型管理 — 分类与后缀")
        self.resize(940, 720)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        hint = QLabel(
            "左边是分类，右边是该分类下的文件后缀。可以自己加后缀、建新分类，"
            "也可以<b>从本机已安装的软件里扫描</b>导入。"
            "<br>这里的设置会覆盖内置规则，并影响列表分类与自动归档。"
        )
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        bar = QHBoxLayout()
        self.btn_scan = QPushButton("从本机软件扫描…")
        self.btn_scan.setObjectName("Primary")
        self.btn_scan.clicked.connect(self._open_scan)
        bar.addWidget(self.btn_scan)

        self.btn_new = QPushButton("新建分类…")
        self.btn_new.clicked.connect(self._new_category)
        bar.addWidget(self.btn_new)

        self.btn_del_cat = QPushButton("删除分类")
        self.btn_del_cat.clicked.connect(self._delete_category)
        bar.addWidget(self.btn_del_cat)

        bar.addStretch(1)
        self.btn_reset = QPushButton("恢复默认规则")
        self.btn_reset.clicked.connect(self._reset)
        bar.addWidget(self.btn_reset)
        root.addLayout(bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.cat_list = QListWidget()
        self.cat_list.setObjectName("CategoryList")
        self.cat_list.currentItemChanged.connect(lambda *_: self._refresh_exts())
        splitter.addWidget(self.cat_list)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(6)
        self.lbl_cat = QLabel("")
        self.lbl_cat.setObjectName("SectionTitle")
        rl.addWidget(self.lbl_cat)

        self.ext_list = QListWidget()
        self.ext_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        rl.addWidget(self.ext_list, 1)

        ext_bar = QHBoxLayout()
        self.btn_add_ext = QPushButton("添加后缀…")
        self.btn_add_ext.clicked.connect(self._add_exts)
        ext_bar.addWidget(self.btn_add_ext)
        self.btn_del_ext = QPushButton("移出到「其他」")
        self.btn_del_ext.clicked.connect(self._remove_exts)
        ext_bar.addWidget(self.btn_del_ext)
        ext_bar.addStretch(1)
        self.lbl_count = QLabel("")
        self.lbl_count.setObjectName("Hint")
        ext_bar.addWidget(self.lbl_count)
        rl.addLayout(ext_bar)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 620])
        root.addWidget(splitter, 1)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.buttons.accepted.connect(self._save)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)

        self._refresh_categories()

    # ------------------------------------------------------------------
    # 列表刷新
    # ------------------------------------------------------------------

    def _categories(self) -> list[str]:
        builtin = [c for c in CATEGORY_ORDER if c != "其他"]
        names = [c["name"] for c in self.custom]
        return builtin + names + ["其他"]

    def _refresh_categories(self, keep: str | None = None) -> None:
        current = keep or (self.cat_list.currentItem().data(Qt.ItemDataRole.UserRole)
                           if self.cat_list.currentItem() else None)
        self.cat_list.blockSignals(True)
        self.cat_list.clear()
        for cat in self._categories():
            n = sum(1 for c in self.ext_map.values() if c == cat)
            label = f"{self._icon(cat)}  {cat}"
            if n:
                label += f"   {n}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, cat)
            self.cat_list.addItem(item)
        self.cat_list.blockSignals(False)

        row = 0
        for i in range(self.cat_list.count()):
            if self.cat_list.item(i).data(Qt.ItemDataRole.UserRole) == current:
                row = i
                break
        self.cat_list.setCurrentRow(row)
        self._refresh_exts()

    def _icon(self, cat: str) -> str:
        for c in self.custom:
            if c["name"] == cat:
                return c.get("icon") or "🗂️"
        return icon_for(cat)

    def _current_cat(self) -> str:
        item = self.cat_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else "其他"

    def _refresh_exts(self) -> None:
        cat = self._current_cat()
        self.lbl_cat.setText(f"{self._icon(cat)}  {cat}")
        exts = sorted(e for e, c in self.ext_map.items() if c == cat)
        self.ext_list.clear()
        self.ext_list.addItems(exts)
        self.lbl_count.setText(f"{len(exts)} 个后缀")
        is_custom = cat in {c["name"] for c in self.custom}
        self.btn_del_cat.setEnabled(is_custom)
        self.btn_del_ext.setEnabled(cat != "其他" and bool(exts))

    # ------------------------------------------------------------------
    # 编辑操作
    # ------------------------------------------------------------------

    def _add_exts(self) -> None:
        cat = self._current_cat()
        text, ok = QInputDialog.getText(
            self, "添加后缀",
            f"要归到「{cat}」的后缀（可一次填多个，用空格或逗号分隔）：\n"
            "例如：.abc  或者  abc .def",
        )
        if not ok or not text.strip():
            return
        raw = text.replace(",", " ").replace("，", " ").replace(";", " ").split()
        added = 0
        for token in raw:
            ext = token.strip().lower()
            if not ext:
                continue
            if not ext.startswith("."):
                ext = "." + ext
            if len(ext) < 2 or any(ch in ext for ch in '\\/:*?"<>| '):
                continue
            self.ext_map[ext] = cat
            added += 1
        if added:
            self.changed = True
            self._refresh_categories(keep=cat)
        else:
            QMessageBox.information(self, "添加后缀", "没有解析出有效的后缀。")

    def _remove_exts(self) -> None:
        cat = self._current_cat()
        if cat == "其他":
            return
        picked = [i.text() for i in self.ext_list.selectedItems()]
        if not picked:
            QMessageBox.information(self, "移出", "请先在右边选中要移出的后缀。")
            return
        for ext in picked:
            self.ext_map[ext] = "其他"
        self.changed = True
        self._refresh_categories(keep=cat)

    def _new_category(self) -> None:
        name, ok = QInputDialog.getText(self, "新建分类", "分类名称：")
        if not ok or not name.strip():
            return
        name = name.strip()
        if name in self._categories():
            QMessageBox.information(self, "新建分类", f"「{name}」已经存在了。")
            return
        icon, ok = QInputDialog.getItem(
            self, "选择图标", f"给「{name}」选一个图标：", list(CUSTOM_ICON_CHOICES), 0, False
        )
        if not ok:
            return
        self.custom.append({"name": name, "icon": icon})
        self.changed = True
        self._refresh_categories(keep=name)

    def _delete_category(self) -> None:
        cat = self._current_cat()
        if cat not in {c["name"] for c in self.custom}:
            return
        n = sum(1 for c in self.ext_map.values() if c == cat)
        ok = QMessageBox.question(
            self, "删除分类",
            f"确定删除分类「{cat}」吗？\n"
            f"它下面现在有 {n} 个后缀，这些后缀会被移到「其他」。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ok != QMessageBox.StandardButton.Yes:
            return
        self.custom = [c for c in self.custom if c["name"] != cat]
        for ext, c in list(self.ext_map.items()):
            if c == cat:
                self.ext_map[ext] = "其他"
        self.changed = True
        self._refresh_categories(keep="其他")

    def _open_scan(self) -> None:
        dlg = ScanDialog(self.ext_map, self._categories(), self)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.picked:
            return
        for ext, cat in dlg.picked:
            self.ext_map[ext.lower()] = cat
        self.changed = True
        self._refresh_categories()
        self.lbl_cat.setText(f"{self.lbl_cat.text()}   已加入 {len(dlg.picked)} 个后缀")

    def _reset(self) -> None:
        ok = QMessageBox.question(
            self, "恢复默认规则",
            "会丢掉你自定义的分类和后缀映射，恢复成程序内置的规则。\n是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ok != QMessageBox.StandardButton.Yes:
            return
        self.custom = []
        self.ext_map = dict(EXT_TO_CATEGORY)
        self.changed = True
        self._refresh_categories(keep="文档")

    # ------------------------------------------------------------------

    def _save(self) -> None:
        # 只记录与内置不同的部分，免得配置文件里塞 300 多行
        self.cfg.ext_overrides = CategoryMap().to_overrides(self.ext_map)
        self.cfg.custom_categories = list(self.custom)
        self.cfg.save()
        self.accept()
